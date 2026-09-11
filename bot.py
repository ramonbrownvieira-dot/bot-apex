import asyncio
import json
import websockets
import os
import threading
from flask import Flask

app = Flask(__name__)

# -------------------------------------------------------------------
# BANCA FICTÍCIA E PARÂMETROS OPERACIONAIS DA MAINNET
# -------------------------------------------------------------------
SALDO_BANCA_USDT = 100.00                                  # Banca inicial fictícia
CAPITAL_POR_LADO = 10.00                                   # Margem fictícia por lado (US$ 10.00)
LEVERAGE = 10                                              # Alavancagem 10x

# MODELO 85/15 COM PARCIAL DE 0.50%
PARCIAL_PCT = 0.0050                                       # Parcial a 0.50%
PCT_FECHAR_VENCEDOR = 0.85                                 # Realiza 85% do vencedor
PCT_FECHAR_PERDEDOR = 0.15                                 # Descarta 15% do perdedor

TAXA_TAKER_BINANCE = 0.0005                                # Taxa Taker real da Binance (0.05% por ordem)

EXPOSICAO_LIQUIDA = PCT_FECHAR_PERDEDOR - PCT_FECHAR_VENCEDOR # -0.70
SALDO_BRUTO_PARCIAL = (PCT_FECHAR_VENCEDOR - PCT_FECHAR_PERDEDOR) * PARCIAL_PCT
CALC_TRAVA = PARCIAL_PCT + ((SALDO_BRUTO_PARCIAL - (TAXA_TAKER_BINANCE * 4)) / abs(EXPOSICAO_LIQUIDA))

TRAVA_0X0_PCT = round(CALC_TRAVA, 6)                      # ~0.80% total da entrada
ALVO_FINAL_PCT = round(PARCIAL_PCT / 2.0, 6)              # 0.25% (Repique na metade)

COOLDOWN_SEGUNDOS = 180                                    # Cooldown de 3 minutos

WS_URL = "wss://fstream.binance.com/ws/btcusdt@ticker"

@app.route('/')
def health_check():
    return f"Bot APEX Paper Trading Mainnet Direct WS | Saldo: ${SALDO_BANCA_USDT:.2f} USDT", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

async def obter_proximo_preco_ws(ws):
    msg = await ws.recv()
    data = json.loads(msg)
    return float(data['c']) # 'c' é o último preço negociado no ticker

async def executar_ciclo_paper_nativo():
    global SALDO_BANCA_USDT
    print(f"\n🌐 [MAINNET DIRECT WEBSOCKET] Conectando a stream nativa da Binance Futures...", flush=True)
    print(f"💰 Saldo da Banca Simulada: ${SALDO_BANCA_USDT:.2f} USDT", flush=True)

    async with websockets.connect(WS_URL) as ws:
        # 1. Capturar o primeiro tick real para entrada
        p_ref = await obter_proximo_preco_ws(ws)
        
        nocional_total = (CAPITAL_POR_LADO * LEVERAGE) * 2
        taxa_abertura = nocional_total * TAXA_TAKER_BINANCE
        SALDO_BANCA_USDT -= taxa_abertura

        p_parcial_baixa = p_ref * (1.0 - PARCIAL_PCT)
        p_0x0_baixa = p_ref * (1.0 - TRAVA_0X0_PCT)
        p_alvo_baixa = p_ref * (1.0 - ALVO_FINAL_PCT)

        p_parcial_alta = p_ref * (1.0 + PARCIAL_PCT)
        p_0x0_alta = p_ref * (1.0 + TRAVA_0X0_PCT)
        p_alvo_alta = p_ref * (1.0 + ALVO_FINAL_PCT)

        print(f"✅ [ENTRADA NATIVA WS] PMP Mainnet: {p_ref:.2f} | Taxa Abertura: -${taxa_abertura:.4f} USDT", flush=True)
        print(f"📌 Queda -> Parcial: {p_parcial_baixa:.2f} | 0x0 Limite: {p_0x0_baixa:.2f} | Alvo Repique: {p_alvo_baixa:.2f}", flush=True)
        print(f"📌 Alta  -> Parcial: {p_parcial_alta:.2f} | 0x0 Limite: {p_0x0_alta:.2f} | Alvo Repique: {p_alvo_alta:.2f}", flush=True)
        print("⚡ [STREAM DIRETA ATIVA] Ouvindo cotações de alta velocidade sem HTTP REST...", flush=True)

        lado_atingido = None

        # 2. FASE 1: Monitoramento via Stream Nativa
        while True:
            p_mkt = await obter_proximo_preco_ws(ws)

            if p_mkt <= p_parcial_baixa:
                print(f"🎯 [PUSH DIRECT WS] Cotação Real {p_mkt:.2f} <= Parcial Queda {p_parcial_baixa:.2f}!", flush=True)
                lado_atingido = 'QUEDA'
                break

            if p_mkt >= p_parcial_alta:
                print(f"🎯 [PUSH DIRECT WS] Cotação Real {p_mkt:.2f} >= Parcial Alta {p_parcial_alta:.2f}!", flush=True)
                lado_atingido = 'ALTA'
                break

            if p_mkt <= p_0x0_baixa or p_mkt >= p_0x0_alta:
                print(f"🏁 Trava 0x0 atingida na Fase 1! Cotação: {p_mkt:.2f}", flush=True)
                taxa_saida = nocional_total * TAXA_TAKER_BINANCE
                SALDO_BANCA_USDT -= taxa_saida
                print(f"🛑 Operação encerrada no 0x0. Saldo Banca: ${SALDO_BANCA_USDT:.2f} USDT\n", flush=True)
                return

        # 3. FASE 2: Liquidação da Parcial + Acompanhamento do Repique
        if lado_atingido:
            lucro_bruto_parcial = (CAPITAL_POR_LADO * LEVERAGE) * (PCT_FECHAR_VENCEDOR - PCT_FECHAR_PERDEDOR) * PARCIAL_PCT
            taxa_parcial = nocional_total * (PCT_FECHAR_VENCEDOR + PCT_FECHAR_PERDEDOR) / 2.0 * TAXA_TAKER_BINANCE
            lucro_liquido_parcial = lucro_bruto_parcial - taxa_parcial
            
            SALDO_BANCA_USDT += lucro_liquido_parcial
            print(f"🎉 [PARCIAL DISPARADA] Lucro Líquido na Carteira: +${lucro_liquido_parcial:.4f} USDT", flush=True)
            print(f"🚀 [FASE 2 REPIQUE] Acompanhando movimento do preço na Mainnet...", flush=True)

            while True:
                p_mkt = await obter_proximo_preco_ws(ws)

                if lado_atingido == 'QUEDA':
                    if p_mkt >= p_alvo_baixa:
                        lucro_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * (PARCIAL_PCT - ALVO_FINAL_PCT)
                        taxa_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * TAXA_TAKER_BINANCE
                        ganho_final = lucro_repique - taxa_repique
                        SALDO_BANCA_USDT += ganho_final
                        print(f"🏆 [REPIQUE CONCLUÍDO!] Ganho Final Depositado: +${ganho_final:.4f} USDT", flush=True)
                        break
                    elif p_mkt <= p_0x0_baixa:
                        print(f"🛡️ Saída na Trava 0x0 do Repique. Lucro da Parcial mantido no caixa!", flush=True)
                        break

                elif lado_atingido == 'ALTA':
                    if p_mkt <= p_alvo_alta:
                        lucro_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * (PARCIAL_PCT - ALVO_FINAL_PCT)
                        taxa_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * TAXA_TAKER_BINANCE
                        ganho_final = lucro_repique - taxa_repique
                        SALDO_BANCA_USDT += ganho_final
                        print(f"🏆 [REPIQUE CONCLUÍDO!] Ganho Final Depositado: +${ganho_final:.4f} USDT", flush=True)
                        break
                    elif p_mkt >= p_0x0_alta:
                        print(f"🛡️ Saída na Trava 0x0 do Repique. Lucro da Parcial mantido no caixa!", flush=True)
                        break

            print(f"📊 [RESULTADO DO CICLO] Saldo Atual da Banca: ${SALDO_BANCA_USDT:.2f} USDT\n", flush=True)

async def main_loop():
    while True:
        try:
            await executar_ciclo_paper_nativo()
            print(f"⏳ Cooldown de {COOLDOWN_SEGUNDOS/60:.1f} minutos para o próximo ciclo...\n", flush=True)
            await asyncio.sleep(COOLDOWN_SEGUNDOS)
        except Exception as e:
            print(f"⚠️ Erro no ciclo Mainnet WebSocket: {e}", flush=True)
            await asyncio.sleep(10)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main_loop())
