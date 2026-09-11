import asyncio
import json
import websockets
import os
import sys
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

def log_instantaneo(mensagem):
    print(mensagem, flush=True)
    sys.stdout.flush()

@app.route('/')
def health_check():
    return f"Bot APEX Paper Trading Mainnet Direct WS | Saldo: ${SALDO_BANCA_USDT:.2f} USDT", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

async def obter_proximo_preco_ws(ws):
    msg = await ws.recv()
    data = json.loads(msg)
    return float(data['c']) # 'c' é o último preço negociado no ticker

async def executar_ciclo_paper_nativo():
    global SALDO_BANCA_USDT
    log_instantaneo(f"\n🌐 [MAINNET DIRECT WEBSOCKET] Conectando a stream nativa da Binance Futures...")
    log_instantaneo(f"💰 Saldo da Banca Simulada: ${SALDO_BANCA_USDT:.2f} USDT")

    async with websockets.connect(WS_URL) as ws:
        # 1. Capturar o primeiro tick real para entrada
        log_instantaneo("⏳ Aguardando recebimento do primeiro tick da Binance...")
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

        log_instantaneo(f"✅ [ENTRADA NATIVA WS] PMP Mainnet: {p_ref:.2f} | Taxa Abertura: -${taxa_abertura:.4f} USDT")
        log_instantaneo(f"📌 Queda -> Parcial: {p_parcial_baixa:.2f} | 0x0 Limite: {p_0x0_baixa:.2f} | Alvo Repique: {p_alvo_baixa:.2f}")
        log_instantaneo(f"📌 Alta  -> Parcial: {p_parcial_alta:.2f} | 0x0 Limite: {p_0x0_alta:.2f} | Alvo Repique: {p_alvo_alta:.2f}")
        log_instantaneo("⚡ [STREAM DIRETA ATIVA] Monitorando preços em tempo real...")

        lado_atingido = None

        # 2. FASE 1: Monitoramento via Stream Nativa
        contador_ticks = 0
        while True:
            p_mkt = await obter_proximo_preco_ws(ws)
            contador_ticks += 1

            # Log Heartbeat a cada 30 ticks para confirmar funcionamento
            if contador_ticks % 30 == 0:
                log_instantaneo(f"💓 [HEARTBEAT WS] Cotação Atual BTC: {p_mkt:.2f}")

            if p_mkt <= p_parcial_baixa:
                log_instantaneo(f"🎯 [PUSH DIRECT WS] Cotação Real {p_mkt:.2f} <= Parcial Queda {p_parcial_baixa:.2f}!")
                lado_atingido = 'QUEDA'
                break

            if p_mkt >= p_parcial_alta:
                log_instantaneo(f"🎯 [PUSH DIRECT WS] Cotação Real {p_mkt:.2f} >= Parcial Alta {p_parcial_alta:.2f}!")
                lado_atingido = 'ALTA'
                break

            if p_mkt <= p_0x0_baixa or p_mkt >= p_0x0_alta:
                log_instantaneo(f"🏁 Trava 0x0 atingida na Fase 1! Cotação: {p_mkt:.2f}")
                taxa_saida = nocional_total * TAXA_TAKER_BINANCE
                SALDO_BANCA_USDT -= taxa_saida
                log_instantaneo(f"🛑 Operação encerrada no 0x0. Saldo Banca: ${SALDO_BANCA_USDT:.2f} USDT\n")
                return

        # 3. FASE 2: Liquidação da Parcial + Acompanhamento do Repique
        if lado_atingido:
            lucro_bruto_parcial = (CAPITAL_POR_LADO * LEVERAGE) * (PCT_FECHAR_VENCEDOR - PCT_FECHAR_PERDEDOR) * PARCIAL_PCT
            taxa_parcial = nocional_total * (PCT_FECHAR_VENCEDOR + PCT_FECHAR_PERDEDOR) / 2.0 * TAXA_TAKER_BINANCE
            lucro_liquido_parcial = lucro_bruto_parcial - taxa_parcial
            
            SALDO_BANCA_USDT += lucro_liquido_parcial
            log_instantaneo(f"🎉 [PARCIAL DISPARADA] Lucro Líquido na Carteira: +${lucro_liquido_parcial:.4f} USDT")
            log_instantaneo(f"🚀 [FASE 2 REPIQUE] Acompanhando movimento do preço na Mainnet...")

            while True:
                p_mkt = await obter_proximo_preco_ws(ws)

                if lado_atingido == 'QUEDA':
                    if p_mkt >= p_alvo_baixa:
                        lucro_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * (PARCIAL_PCT - ALVO_FINAL_PCT)
                        taxa_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * TAXA_TAKER_BINANCE
                        ganho_final = lucro_repique - taxa_repique
                        SALDO_BANCA_USDT += ganho_final
                        log_instantaneo(f"🏆 [REPIQUE CONCLUÍDO!] Ganho Final Depositado: +${ganho_final:.4f} USDT")
                        break
                    elif p_mkt <= p_0x0_baixa:
                        log_instantaneo(f"🛡️ Saída na Trava 0x0 do Repique. Lucro da Parcial mantido no caixa!")
                        break

                elif lado_atingido == 'ALTA':
                    if p_mkt <= p_alvo_alta:
                        lucro_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * (PARCIAL_PCT - ALVO_FINAL_PCT)
                        taxa_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * TAXA_TAKER_BINANCE
                        ganho_final = lucro_repique - taxa_repique
                        SALDO_BANCA_USDT += ganho_final
                        log_instantaneo(f"🏆 [REPIQUE CONCLUÍDO!] Ganho Final Depositado: +${ganho_final:.4f} USDT")
                        break
                    elif p_mkt >= p_0x0_alta:
                        log_instantaneo(f"🛡️ Saída na Trava 0x0 do Repique. Lucro da Parcial mantido no caixa!")
                        break

            log_instantaneo(f"📊 [RESULTADO DO CICLO] Saldo Atual da Banca: ${SALDO_BANCA_USDT:.2f} USDT\n")

async def main_loop():
    log_instantaneo("🤖 Bot APEX Paper Trader Iniciando Event Loop...")
    while True:
        try:
            await executar_ciclo_paper_nativo()
            log_instantaneo(f"⏳ Cooldown de {COOLDOWN_SEGUNDOS/60:.1f} minutos para o próximo ciclo...\n")
            await asyncio.sleep(COOLDOWN_SEGUNDOS)
        except Exception as e:
            log_instantaneo(f"⚠️ Erro no ciclo Mainnet WebSocket: {e}")
            await asyncio.sleep(10)

def iniciar_bot():
    asyncio.run(main_loop())

if __name__ == '__main__':
    # Inicia a thread do Bot e força flush nos logs
    t = threading.Thread(target=iniciar_bot, daemon=True)
    t.start()
    log_instantaneo("🚀 Servidor Flask e Thread de Trading disparados!")
    run_flask()
