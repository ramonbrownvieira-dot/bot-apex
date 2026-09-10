import ccxt
import time
import threading
import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot APEX está rodando 24/7!", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True
    }
})

exchange.enable_demo_trading(True)

SYMBOL = 'BTC/USDT'
LEVERAGE = 10
CAPITAL_USDT = float(os.getenv('CAPITAL_USDT', 5.0))     # US$ 5.00 por lado

# -------------------------------------------------------------------
# MODELO PRÁTICO (PARCIAL DE 0.50% NO BTC/USDT)
# -------------------------------------------------------------------
PARCIAL_PCT = float(os.getenv('PARCIAL_PCT', 0.0050))     # 0.50%
TAXA_ESTIMADA_PCT = 0.0020                                 # Taxas (0.20%)

# DERIVAÇÃO MATEMÁTICA RECALIBRADA
TRAVA_0X0_PCT = round((PARCIAL_PCT * 1.6941) + TAXA_ESTIMADA_PCT, 6) # 1.0471%
ALVO_FINAL_PCT = round(PARCIAL_PCT / 2.0, 6)                         # Repique na metade (0.25%)

COOLDOWN_SEGUNDOS = 600

def obter_preco_executado_real(ordem_id, preco_fallback):
    """Consulta os fills de trade na Binance para calcular o PMP real."""
    if not ordem_id:
        return preco_fallback

    for _ in range(3):
        try:
            trades = exchange.fetch_my_trades(SYMBOL, params={'orderId': str(ordem_id)})
            if trades:
                total_qty = sum(float(t['amount']) for t in trades)
                if total_qty > 0:
                    total_cost = sum(float(t['amount']) * float(t['price']) for t in trades)
                    return total_cost / total_qty
        except Exception as e:
            print(f"⚠️ Aguardando Fills na Binance para ordem {ordem_id}... ({e})", flush=True)
        time.sleep(0.5)

    return preco_fallback

def obter_preco_atual():
    try:
        ticker = exchange.fetch_ticker(SYMBOL)
        return float(ticker['last'])
    except Exception as e:
        print(f"⚠️ Erro ao consultar preço de mercado: {e}", flush=True)
        return None

def checar_status_ordem(ordem_id):
    try:
        ordem = exchange.fetch_order(ordem_id, SYMBOL)
        return ordem.get('status')
    except Exception as e:
        return 'open'

def executar_ciclo():
    print(f"🚀 [FASE 1] Executando entradas a mercado no par {SYMBOL} ($5/lado) e armando ordens...", flush=True)
    
    exchange.load_markets()
    
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
    except Exception as e:
        print(f"⚠️ Alerta ao definir alavancagem: {e}", flush=True)
    
    precio_atual = obter_preco_atual()
    qtd_moedas_raw = (CAPITAL_USDT * LEVERAGE) / precio_atual
    qtd_moedas = float(exchange.amount_to_precision(SYMBOL, qtd_moedas_raw))
    
    # 1. Abertura Long/Short
    ordem_long = exchange.create_market_buy_order(SYMBOL, qtd_moedas, {'positionSide': 'LONG'})
    ordem_short = exchange.create_market_sell_order(SYMBOL, qtd_moedas, {'positionSide': 'SHORT'})
    
    time.sleep(0.5)
    
    # 2. Preço Médio Ponderado ($P_ref$) Real via Fills
    p_long = obter_preco_executado_real(ordem_long.get('id'), precio_atual)
    p_short = obter_preco_executado_real(ordem_short.get('id'), precio_atual)
    p_ref = (p_long + p_short) / 2.0
    
    print(f"✅ Execução Real Fills: Long {p_long:.2f} | Short {p_short:.2f} | Preço Ref PMP: {p_ref:.2f}", flush=True)
    
    # 3. Níveis de Preço com Parcial a 0,50% e 0x0 Real com Taxas
    p_parcial_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - PARCIAL_PCT)))
    p_0x0_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - TRAVA_0X0_PCT)))
    p_alvo_baixa = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - ALVO_FINAL_PCT)))
    
    p_parcial_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + PARCIAL_PCT)))
    p_0x0_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + TRAVA_0X0_PCT)))
    p_alvo_alta = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 + ALVO_FINAL_PCT)))
    
    qtd_parcial_short = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.85))
    qtd_parcial_long = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.30))
    qtd_total = float(exchange.amount_to_precision(SYMBOL, qtd_moedas))
    
    print(f"📊 Configuração: Parcial {PARCIAL_PCT*100:.2f}% | Trava 0x0 c/ Taxas {TRAVA_0X0_PCT*100:.4f}% | Alvo Repique {ALVO_FINAL_PCT*100:.3f}%", flush=True)
    print(f"📌 Queda -> Parcial: {p_parcial_baixa:.2f} | 0x0 Real: {p_0x0_baixa:.2f} | Alvo Repique: {p_alvo_baixa:.2f}", flush=True)
    print(f"📌 Alta  -> Parcial: {p_parcial_alta:.2f} | 0x0 Real: {p_0x0_alta:.2f} | Alvo Repique: {p_alvo_alta:.2f}", flush=True)
    
    # 4. Posicionar Ordens Condicionais Iniciais
    # Lado da Queda
    o_p_baixa_short = exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_parcial_short, None, {
        'positionSide': 'SHORT', 'stopPrice': p_parcial_baixa, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_parcial_long, None, {
        'positionSide': 'LONG', 'stopPrice': p_parcial_baixa, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_total, None, {
        'positionSide': 'SHORT', 'stopPrice': p_0x0_baixa, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_total, None, {
        'positionSide': 'LONG', 'stopPrice': p_0x0_baixa, 'workingType': 'MARK_PRICE'
    })
    
    # Lado da Alta
    o_p_alta_long = exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_parcial_long, None, {
        'positionSide': 'LONG', 'stopPrice': p_parcial_alta, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_parcial_short, None, {
        'positionSide': 'SHORT', 'stopPrice': p_parcial_alta, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_total, None, {
        'positionSide': 'SHORT', 'stopPrice': p_0x0_alta, 'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_total, None, {
        'positionSide': 'LONG', 'stopPrice': p_0x0_alta, 'workingType': 'MARK_PRICE'
    })
    
    id_p_baixa = str(o_p_baixa_short['id'])
    id_p_alta = str(o_p_alta_long['id'])
    
    print("⏳ [FASE 1 OK] Ordens armadas no book do BTC/USDT. Monitorando execuções reais...", flush=True)
    
    time.sleep(10)
    
    # 5. Monitoramento Fiel do Status das Parciais
    lado_atingido = None
    
    while True:
        status_alta = checar_status_ordem(id_p_alta)
        status_baixa = checar_status_ordem(id_p_baixa)
        p_mercado = obter_preco_atual()
        
        if status_alta in ['closed', 'filled']:
            print(f"🎯 PARCIAL DE ALTA CONFIRMADA NA BINANCE!", flush=True)
            lado_atingido = 'ALTA'
            break
            
        if status_baixa in ['closed', 'filled']:
            print(f"🎯 PARCIAL DE QUEDA CONFIRMADA NA BINANCE!", flush=True)
            lado_atingido = 'QUEDA'
            break
            
        if p_mercado and (p_mercado <= p_0x0_baixa or p_mercado >= p_0x0_alta):
            print(f"🏁 Trava 0x0 atingida no preço! Cotação: {p_mercado:.2f}", flush=True)
            try:
                exchange.cancel_all_orders(SYMBOL)
            except:
                pass
            return
            
        time.sleep(3)
    
    # 6. FASE 2: Expurgar ordens lixo e armar o Repique Limpo
    if lado_atingido:
        print(f"🧹 Expurgando ordens antigas do book (Close All Lixo)...", flush=True)
        try:
            exchange.cancel_all_orders(SYMBOL)
            print("✅ Book totalmente limpo!", flush=True)
        except Exception as e:
            print(f"⚠️ Alerta ao cancelar ordens antigas: {e}", flush=True)
            
        print(f"🚀 [FASE 2] Posicionando Alvo de Repique de {lado_atingido}...", flush=True)
        
        qtd_alvo_short = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.15))
        qtd_alvo_long = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.70))
        
        try:
            if lado_atingido == 'QUEDA':
                exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_alvo_short, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_alvo_baixa, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_alvo_long, None, {
                    'positionSide': 'LONG', 'stopPrice': p_alvo_baixa, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_total, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_0x0_baixa, 'workingType': 'MARK_PRICE'
                })
            elif lado_atingido == 'ALTA':
                exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qtd_alvo_long, None, {
                    'positionSide': 'LONG', 'stopPrice': p_alvo_alta, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_alvo_short, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_alvo_alta, 'workingType': 'MARK_PRICE'
                })
                exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_total, None, {
                    'positionSide': 'SHORT', 'stopPrice': p_0x0_alta, 'workingType': 'MARK_PRICE'
                })
            print("🛡️ [FASE 2 OK] Alvo e Trava 0x0 do repique armados no book!", flush=True)
        except Exception as e:
            print(f"⚠️ Alerta ao posicionar alvo final: {e}", flush=True)
            
        while True:
            try:
                ordens_ativas = exchange.fetch_open_orders(SYMBOL)
                if len(ordens_ativas) == 0:
                    print(f"🏁 Operação de {lado_atingido} finalizada no Repique/0x0!", flush=True)
                    break
            except:
                pass
            time.sleep(5)

def loop_bot():
    print("🤖 Bot APEX iniciado na nuvem (Europa - Demo Trading)...", flush=True)
    while True:
        try:
            executar_ciclo()
            print(f"⏳ Operação concluída. Aguardando Cooldown de {COOLDOWN_SEGUNDOS/60} minutos...\n", flush=True)
            time.sleep(COOLDOWN_SEGUNDOS)
        except Exception as e:
            print(f"⚠️ Erro no ciclo: {e}", flush=True)
            time.sleep(15)

if __name__ == '__main__':
    t = threading.Thread(target=loop_bot, daemon=True)
    t.start()
    run_flask()
