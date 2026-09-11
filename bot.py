import asyncio
import ccxt.pro as ccxtpro
import os
import threading
from flask import Flask

app = Flask(__name__)

# -------------------------------------------------------------------
# BANCA FICTÍCIA DE PAPER TRADING (SEM USAR API KEYS REAIS PARA ORDENS)
# -------------------------------------------------------------------
SALDO_BANCA_USDT = 100.00                                  # Banca inicial fictícia em dólares
CAPITAL_POR_LADO = 10.00                                   # US$ 10,00 por lado (Long / Short)
LEVERAGE = 10                                              # Alavancagem 10x

# MODELO DEFINITIVO 85/15 A 0.50%
PARCIAL_PCT = 0.0050                                       # Parcial em 0.50%
PCT_FECHAR_VENCEDOR = 0.85                                 # 85%
PCT_FECHAR_PERDEDOR = 0.15                                 # 15%

TAXA_TAKER_BINANCE = 0.0005                                # 0.05% por ordem a mercado (0.20% ida e volta)

EXPOSICAO_LIQUIDA = PCT_FECHAR_PERDEDOR - PCT_FECHAR_VENCEDOR # -0.70
SALDO_BRUTO_PARCIAL = (PCT_FECHAR_VENCEDOR - PCT_FECHAR_PERDEDOR) * PARCIAL_PCT
CALC_TRAVA = PARCIAL_PCT + ((SALDO_BRUTO_PARCIAL - (TAXA_TAKER_BINANCE * 4)) / abs(EXPOSICAO_LIQUIDA))

TRAVA_0X0_PCT = round(CALC_TRAVA, 6)                      # ~0.80% total
ALVO_FINAL_PCT = round(PARCIAL_PCT / 2.0, 6)              # 0.25% (Repique na metade)

SYMBOL = os.getenv('SYMBOL', 'BTC/USDT')                  
COOLDOWN_SEGUNDOS = 180                                    # 3 minutos entre ciclos

@app.route('/')
def health_check():
    return f"Bot APEX Paper Trading Real-Time | Saldo: ${SALDO_BANCA_USDT:.2f} USDT", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

async def executar_ciclo_paper(exchange):
    global SALDO_BANCA_USDT
    print(f"\n🎮 [PAPER TRADING REAL-TIME] Iniciando simulado no par {SYMBOL}...", flush=True)
    print(f"💰 Saldo Atual da Banca Fictícia: ${SALDO_BANCA_USDT:.2f} USDT", flush=True)

    # 1. Obter Preço de Mercado Real via WebSocket
    ticker = await exchange.fetch_ticker(SYMBOL)
    p_ref = float(ticker['last'])
    
    # Cálculo das taxas de abertura (Long + Short)
    nocional_total = (CAPITAL_POR_LADO * LEVERAGE) * 2     # Ex: $200 USD nocional
    taxa_abertura = nocional_total * TAXA_TAKER_BINANCE     # Taxa real paga na abertura
    SALDO_BANCA_USDT -= taxa_abertura

    # Níveis de Preço com base na Cotação Real de Mercado
    p_parcial_baixa = p_ref * (1.0 - PARCIAL_PCT)
    p_0x0_baixa = p_ref * (1.0 - TRAVA_0X0_PCT)
    p_alvo_baixa = p_ref * (1.0 - ALVO_FINAL_PCT)

    p_parcial_alta = p_ref * (1.0 + PARCIAL_PCT)
    p_0x0_alta = p_ref * (1.0 + TRAVA_0X0_PCT)
    p_alvo_alta = p_ref * (1.0 + ALVO_FINAL_PCT)

    print(f"✅ [ABERTURA SIMULADA] Entrada PMP Real: {p_ref:.2f} | Taxa Abertura: -${taxa_abertura:.4f} USDT", flush=True)
    print(f"📌 Níveis Queda -> Parcial: {p_parcial_baixa:.2f} | 0x0 Limite: {p_0x0_baixa:.2f} | Alvo Repique: {p_alvo_baixa:.2f}", flush=True)
    print(f"📌 Níveis Alta  -> Parcial: {p_parcial_alta:.2f} | 0x0 Limite: {p_0x0_alta:.2f} | Alvo Repique: {p_alvo_alta:.2f}", flush=True)
    print("⚡ [WEBSOCKET REAL ATIVO] Monitorando cotação em tempo real da Binance Produção...", flush=True)

    lado_atingido = None

    # 2. FASE 1: Escuta Ativa de Preço Real via WebSocket Stream
    while True:
        try:
            # Recebe o preço real de mercado no milissegundo em que muda na Binance
            ticker = await exchange.watch_ticker(SYMBOL)
            p_mkt = float(ticker['last'])

            # Teste do Gatilho de Queda
            if p_mkt <= p_parcial_baixa:
                print(f"🎯 [GATILHO REAL WS] Cotação Real {p_mkt:.2f} <= Parcial Queda {p_parcial_baixa:.2f}!", flush=True)
                lado_atingido = 'QUEDA'
                break

            # Teste do Gatilho de Alta
            if p_mkt >= p_parcial_alta:
                print(f"🎯 [GATILHO REAL WS] Cotação Real {p_mkt:.2f} >= Parcial Alta {p_parcial_alta:.2f}!", flush=True)
                lado_atingido = 'ALTA'
                break

            # Trava 0x0 na Fase 1
            if p_mkt <= p_0x0_baixa or p_mkt >= p_0x0_alta:
                print(f"🏁 Trava 0x0 acionada na Fase 1! Cotação: {p_mkt:.2f}", flush=True)
                # Pagamento de taxas de encerramento no 0x0
                taxa_saida = nocional_total * TAXA_TAKER_BINANCE
                SALDO_BANCA_USDT -= taxa_saida
                print(f"🛑 Operação encerrada no 0x0 Real. Saldo Banca: ${SALDO_BANCA_USDT:.2f} USDT\n", flush=True)
                return

        except Exception as e:
            print(f"⚠️ Alerta no Stream WebSocket: {e}", flush=True)
            await asyncio.sleep(1)

    # 3. FASE 2: Liquidação da Parcial + Acompanhamento do Repique em Tempo Real
    if lado_atingido:
        # Liquidação financeira da parcial
        lucro_bruto_parcial = (CAPITAL_POR_LADO * LEVERAGE) * (PCT_FECHAR_VENCEDOR - PCT_FECHAR_PERDEDOR) * PARCIAL_PCT
        taxa_parcial = nocional_total * (PCT_FECHAR_VENCEDOR + PCT_FECHAR_PERDEDOR) / 2.0 * TAXA_TAKER_BINANCE
        lucro_liquido_parcial = lucro_bruto_parcial - taxa_parcial
        
        SALDO_BANCA_USDT += lucro_liquido_parcial
        print(f"🎉 [PARCIAL EXECUTADA] Lucro Líquido Creditado: +${lucro_liquido_parcial:.4f} USDT", flush=True)
        print(f"🚀 [FASE 2 ATIVA] Monitorando Alvo de Repique vs Trava 0x0 em tempo real...", flush=True)

        # Escuta do Repique na Fase 2
        while True:
            try:
                ticker = await exchange.watch_ticker(SYMBOL)
                p_mkt = float(ticker['last'])

                if lado_atingido == 'QUEDA':
                    # Alvo do Repique alcançado
                    if p_mkt >= p_alvo_baixa:
                        lucro_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * (PARCIAL_PCT - ALVO_FINAL_PCT)
                        taxa_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * TAXA_TAKER_BINANCE
                        ganho_final = lucro_repique - taxa_repique
                        SALDO_BANCA_USDT += ganho_final
                        print(f"🏆 [REPIQUE CONCLUÍDO COM SUCESSO!] Ganho Final: +${ganho_final:.4f} USDT", flush=True)
                        break
                    # Trava 0x0 acionada na Fase 2
                    elif p_mkt <= p_0x0_baixa:
                        print(f"🛡️ Operação encerrada na Trava 0x0 do Repique. Lucro da Parcial mantido no caixa!", flush=True)
                        break

                elif lado_atingido == 'ALTA':
                    # Alvo do Repique alcançado
                    if p_mkt <= p_alvo_alta:
                        lucro_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * (PARCIAL_PCT - ALVO_FINAL_PCT)
                        taxa_repique = (CAPITAL_POR_LADO * LEVERAGE) * abs(EXPOSICAO_LIQUIDA) * TAXA_TAKER_BINANCE
                        ganho_final = lucro_repique - taxa_repique
                        SALDO_BANCA_USDT += ganho_final
                        print(f"🏆 [REPIQUE CONCLUÍDO COM SUCESSO!] Ganho Final: +${ganho_final:.4f} USDT", flush=True)
                        break
                    # Trava 0x0 acionada na Fase 2
                    elif p_mkt >= p_0x0_alta:
                        print(f"🛡️ Operação encerrada na Trava 0x0 do Repique. Lucro da Parcial mantido no caixa!", flush=True)
                        break

            except Exception as e:
                print(f"⚠️ Alerta no Stream Fase 2: {e}", flush=True)
                await asyncio.sleep(1)

        print(f"📊 [FIM DE CICLO] Saldo Atualizado da Banca: ${SALDO_BANCA_USDT:.2f} USDT\n", flush=True)

async def main_loop():
    # Conecta diretamente no servidor público de alta performance da Binance Produção (Sem API Keys necessárias para ler ticker)
    exchange = ccxtpro.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })
    try:
        while True:
            try:
                await executar_ciclo_paper(exchange)
                print(f"⏳ Aguardando Cooldown de {COOLDOWN_SEGUNDOS} segundos para o próximo ciclo...\n", flush=True)
                await asyncio.sleep(COOLDOWN_SEGUNDOS)
            except Exception as e:
                print(f"⚠️ Erro no ciclo Paper Trading: {e}", flush=True)
                await asyncio.sleep(10)
    finally:
        await exchange.close()

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main_loop())
