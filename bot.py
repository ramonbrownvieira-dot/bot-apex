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

SYMBOL = 'TUSDT'
LEVERAGE = 10
CAPITAL_USDT = 2.0         # $2 por lado
PARCIAL_PCT = 0.0340       # 3.40%
TRAVA_0X0_PCT = 0.0576     # 5.76%
ALVO_FINAL_PCT = 0.0800    # 8.00%
COOLDOWN_SEGUNDOS = 600    # 10 minutos

def obter_ordens_abertas():
    """Retorna a lista de IDs de ordens condicionais ativas no book."""
    try:
        ordens = exchange.fetch_open_orders(SYMBOL)
        return ordens
    except Exception as e:
        print(f"⚠️ Erro ao consultar ordens abertas: {e}", flush=True)
        return []

def executar_ciclo():
    print("🚀 [FASE 1] Executando entradas e posicionando Parciais e Trava 0x0...", flush=True)
    
    exchange.load_markets()
    
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
    except Exception as e:
        print(f"⚠️ Alerta ao definir alavancagem: {e}", flush=True)
    
    ticker = exchange.fetch_ticker(SYMBOL)
    precio_atual = ticker['last']
    qtd_moedas_raw = (CAPITAL_USDT * LEVERAGE) / precio_atual
    qtd_moedas = float(exchange.amount_to_precision(SYMBOL, qtd_moedas_raw))
    
    # 1. Abertura a Mercado em Hedge Mode
    ordem_long = exchange.create_market_buy_order(SYMBOL, qtd_moedas, {'positionSide': 'LONG'})
    ordem_short = exchange.create_market_sell_order(SYMBOL, qtd_moedas, {'positionSide': 'SHORT'})
    
    p_long = ordem_long.get('average') or precio_atual
    p_short = ordem_short.get('average') or precio_atual
    p_ref = (p_long + p_short) / 2.0
    
    print(f"✅ Entradas: Long {p_long} | Short {p_short} | Preço Ref: {p_ref:.6f}", flush=True)
    
    # 2. Cálculos dos Níveis
    preco_parcial = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - PARCIAL_PCT)))
    preco_0x0 = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - TRAVA_0X0_PCT)))
    preco_alvo = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - ALVO_FINAL_PCT)))
    
    qtd_parcial_short = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.85))
    qtd_parcial_long = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.30))
    qtd_total = float(exchange.amount_to_precision(SYMBOL, qtd_moedas))
    
    print(f"📌 Parcial em: {preco_parcial} | Trava 0x0 em: {preco_0x0}", flush=True)
    
    # 3. Armar Parciais e Trava 0x0 Inicial
    o_parcial_short = exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_parcial_short, None, {
        'positionSide': 'SHORT',
        'stopPrice': preco_parcial,
        'workingType': 'MARK_PRICE'
    })
    
    o_parcial_long = exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_parcial_long, None, {
        'positionSide': 'LONG',
        'stopPrice': preco_parcial,
        'workingType': 'MARK_PRICE'
    })
    
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_total, None, {
        'positionSide': 'SHORT',
        'stopPrice': preco_0x0,
        'workingType': 'MARK_PRICE'
    })
    
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_total, None, {
        'positionSide': 'LONG',
        'stopPrice': preco_0x0,
        'workingType': 'MARK_PRICE'
    })
    
    id_parcial_short = o_parcial_short['id']
    id_parcial_long = o_parcial_long['id']
    
    print("⏳ [FASE 1 OK] Aguardando acionamento da Parcial no mercado...", flush=True)
    time.sleep(10)
    
    # 4. LOOP DE MONITORAMENTO POR ORDENS (Zero falso negativo)
    while True:
        ordens_ativas = obter_ordens_abertas()
        ids_ativas = [str(o['id']) for o in ordens_ativas]
        
        # Se NENHUMA ordem sobrou no book, significa que bateu na Trava 0x0 total
        if len(ids_ativas) == 0:
            print("🏁 Posições e ordens zeradas na Trava 0x0 antes da Parcial.", flush=True)
            return
            
        # Se pelo menos UMA das ordens de parcial sumiu, a Parcial foi executada!
        parcial_short_executada = str(id_parcial_short) not in ids_ativas
        parcial_long_executada = str(id_parcial_long) not in ids_ativas
        
        if parcial_short_executada or parcial_long_executada:
            print("🎯 PARCIAL EXECUTADA PELO MERCADO!", flush=True)
            break
            
        time.sleep(5)
    
    # 5. FASE 2: Posicionar Alvo Final para a posição remanescente
    print("🚀 [FASE 2] Posicionando ordens de Alvo Final e mantendo Trava 0x0...", flush=True)
    
    qtd_alvo_short = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.15))
    qtd_alvo_long = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.70))
    
    try:
        exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_alvo_short, None, {
            'positionSide': 'SHORT',
            'stopPrice': preco_alvo,
            'workingType': 'MARK_PRICE'
        })
        exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_alvo_long, None, {
            'positionSide': 'LONG',
            'stopPrice': preco_alvo,
            'workingType': 'MARK_PRICE'
        })
    except Exception as e:
        print(f"⚠️ Alerta ao posicionar alvo final: {e}", flush=True)
        
    print("🛡️ [FASE 2 OK] Alvos armados! Aguardando liquidação final do ciclo...", flush=True)
    
    # Monitora até todas as ordens terminarem
    while True:
        ordens_remantes = obter_ordens_abertas()
        if len(ordens_remantes) == 0:
            print("🏁 Operação 100% finalizada!", flush=True)
            break
        time.sleep(5)

def loop_bot():
    print("🤖 Bot APEX iniciado na nuvem (Europa - Demo Trading)...", flush=True)
    while True:
        try:
            executar_ciclo()
            print(f"⏳ Iniciando Cooldown de {COOLDOWN_SEGUNDOS/60} minutos para o próximo ciclo...\n", flush=True)
            time.sleep(COOLDOWN_SEGUNDOS)
        except Exception as e:
            print(f"⚠️ Erro no ciclo: {e}", flush=True)
            time.sleep(15)

if __name__ == '__main__':
    t = threading.Thread(target=loop_bot, daemon=True)
    t.start()
    run_flask()
