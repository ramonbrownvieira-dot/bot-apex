import asyncio
import ccxt.pro as ccxtpro
import os
import threading
from flask import Flask

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot APEX WebSocket 0x0 Completo Ativo!", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

SYMBOL = os.getenv('SYMBOL', 'BTC/USDT')                  
LEVERAGE = 10                                             
CAPITAL_USDT = float(os.getenv('CAPITAL_USDT', 10.0))   

# MODO TESTE DE VELOCIDADE (PARCIAL CURTA: 0.15% E REGRA 85/15)
PARCIAL_PCT = 0.0015                                       # 0.15% (Para disparo rápido)
PCT_FECHAR_VENCEDOR = 0.85                                 # 85%
PCT_FECHAR_PERDEDOR = 0.15                                 # 15%

TRAVA_0X0_PCT = 0.0030                                     # Distância da trava 0x0
ALVO_FINAL_PCT = 0.0010                                    # Repique na metade

COOLDOWN_SEGUNDOS = 120

async def iniciar_exchange():
    exchange = ccxtpro.binance({
        'apiKey': os.getenv('BINANCE_API_KEY'),
        'secret': os.getenv('BINANCE_SECRET_KEY'),
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',
            'adjustForTimeDifference': True
        }
    })
    
    try:
        exchange.enable_demo_trading(True)
    except Exception as e:
        print(f"⚠️ Nota Demo Trading: {e}", flush=True)

    return exchange

async def executar_ciclo_ws(exchange):
    print(f"⚡ [TESTE RÁPIDO WS] Iniciando entradas no par {SYMBOL} (Parcial 0.15%)...", flush=True)
    await exchange.load_markets()
    
    try:
        await exchange.set_leverage(LEVERAGE, SYMBOL)
    except Exception as e:
        print(f"⚠️ Alerta Alavancagem: {e}", flush=True)

    ticker = await exchange.fetch_ticker(SYMBOL)
    precio_atual = float(ticker['last'])
    
    qtd_moedas_raw = (CAPITAL_USDT * LEVERAGE) / precio_atual
    qtd_moedas = float(exchange.amount_to_precision(SYMBOL, qtd_moedas_raw))
    if qtd_moedas < 0.002:
        qtd_moedas = 0.002

    # 1. Abertura Long/Short
    ordem_long = await exchange.create_market_buy_order(SYMBOL, qtd_moedas, {'positionSide': 'LONG'})
    ordem_short = await exchange.create_market_sell_order(SYMBOL, qtd_moedas, {'positionSide': 'SHORT'})
    
    await asyncio.sleep(0.5)
    
    p_ref = precio_atual
    
    # 2. Preços dos Níveis
    p_parcial_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - PARCIAL_PCT)))
    p_0x0_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - TRAVA_0X0_PCT)))
    p_alvo_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - ALVO_FINAL_PCT)))
    
    p_parcial_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + PARCIAL_PCT)))
    p_0x0_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + TRAVA_0X0_PCT)))
    p_alvo_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + ALVO_FINAL_PCT)))
    
    qtd_parcial_vencedor = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * PCT_FECHAR_VENCEDOR))
    qtd_parcial_perdedor = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * PCT_FECHAR_PERDEDOR))
    qtd_total = float(exchange.amount_to_precision(SYMBOL, qtd_moedas))

    print(f"📌 TESTE -> Parcial Queda: {p_parcial_baixa} | Parcial Alta: {p_parcial_alta}", flush=True)

    # 3. Armar TODAS as 6 Ordens Condicionais no Book (Parciais + Trava 0x0)
    # Lado da Queda (3 Ordens)
    o_p_baixa = await exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_parcial_vencedor, None, {
        'positionSide': 'SHORT', 'stopPrice': p_parcial_baixa, 'workingType': 'MARK_PRICE'
    })
    await exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_parcial_perdedor, None, {
        'positionSide': 'LONG', 'stopPrice': p_parcial_baixa, 'workingType': 'MARK_PRICE'
    })
    await exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_total, None, {
        'positionSide': 'SHORT', 'stopPrice': p_0x0_baixa, 'workingType': 'MARK_PRICE'
    })
    
    # Lado da Alta (3 Ordens)
    o_p_alta = await exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_parcial_perdedor, None, {
        'positionSide': 'LONG', 'stopPrice': p_parcial_alta, 'workingType': 'MARK_PRICE'
    })
    await exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_parcial_vencedor, None, {
        'positionSide': 'SHORT', 'stopPrice': p_parcial_alta, 'workingType': 'MARK_PRICE'
    })
    await exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_total, None, {
        'positionSide': 'SHORT', 'stopPrice': p_0x0_alta, 'workingType': 'MARK_PRICE'
    })

    id_p_baixa = str(o_p_baixa.get('id'))
    id_p_alta = str(o_p_alta.get('id'))

    print("⚡ [6 ORDENS NO BOOK] Ouvindo execuções via WebSocket Stream...", flush=True)

    # 4. Escuta Ativa Instantânea via WebSocket Push
    lado_atingido = None
    while True:
        try:
            orders = await exchange.watch_orders(SYMBOL)
            for order in orders:
                ord_id = str(order.get('id'))
                status = order.get('status')
                
                if status in ['closed', 'filled']:
                    if ord_id == id_p_baixa:
                        print("🎯 [PUSH WS] Parcial de QUEDA executada na Binance!", flush=True)
                        lado_atingido = 'QUEDA'
                        break
                    elif ord_id == id_p_alta:
                        print("🎯 [PUSH WS] Parcial de ALTA executada na Binance!", flush=True)
                        lado_atingido = 'ALTA'
                        break
            if lado_atingido:
                break
        except Exception as e:
            print(f"⚠️ Alerta no canal WebSocket: {e}", flush=True)
            await asyncio.sleep(1)

    # 5. FASE 2: Expurgar ordens antigas e armar o Repique Limpo
    if lado_atingido:
        print("🧹 Expurgando ordens antigas do book (Close All)...", flush=True)
        try:
            await exchange.cancel_all_orders(SYMBOL)
            print("✅ Book Limpo!", flush=True)
        except Exception as e:
            print(f"⚠️ Alerta ao limpar ordens: {e}", flush=True)

        print(f"🚀 Armando Alvo de Repique da {lado_atingido}...", flush=True)
        qtd_alvo_vencedor = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * (1.0 - PCT_FECHAR_VENCEDOR)))
        qtd_alvo_perdedor = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * (1.0 - PCT_FECHAR_PERDEDOR)))

        if lado_atingido == 'QUEDA':
            await exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_alvo_vencedor, None, {
                'positionSide': 'SHORT', 'stopPrice': p_alvo_baixa, 'workingType': 'MARK_PRICE'
            })
            await exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_alvo_perdedor, None, {
                'positionSide': 'LONG', 'stopPrice': p_alvo_baixa, 'workingType': 'MARK_PRICE'
            })
        elif lado_atingido == 'ALTA':
            await exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_alvo_perdedor, None, {
                'positionSide': 'LONG', 'stopPrice': p_alvo_alta, 'workingType': 'MARK_PRICE'
            })
            await exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_alvo_vencedor, None, {
                'positionSide': 'SHORT', 'stopPrice': p_alvo_alta, 'workingType': 'MARK_PRICE'
            })

        print("🛡️ [FASE 2 OK] Ordens do Repique armadas no book!", flush=True)

async def main_loop():
    exchange = await iniciar_exchange()
    try:
        while True:
            try:
                await executar_ciclo_ws(exchange)
                print(f"⏳ Cooldown de {COOLDOWN_SEGUNDOS} segundos...\n", flush=True)
                await asyncio.sleep(COOLDOWN_SEGUNDOS)
            except Exception as e:
                print(f"⚠️ Erro no ciclo WS: {e}", flush=True)
                await asyncio.sleep(10)
    finally:
        await exchange.close()

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main_loop())
