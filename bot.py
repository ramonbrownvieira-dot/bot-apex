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
CAPITAL_USDT = 2.0         # Funciona para qualquer valor de banca
PARCIAL_PCT = 0.0340       # 3.40%
TRAVA_0X0_PCT = 0.0576     # 5.76%
ALVO_FINAL_PCT = 0.0800    # 8.00%
COOLDOWN_SEGUNDOS = 600    # 10 minutos (após fechamento total)

def obter_preco_atual():
    """Consulta o preço de mercado em tempo real via Ticker (Zero Delay)."""
    try:
        ticker = exchange.fetch_ticker(SYMBOL)
        return float(ticker['last'])
    except Exception as e:
        print(f"⚠️ Erro ao consultar preço de mercado: {e}", flush=True)
        return None

def executar_ciclo():
    print("🚀 [FASE 1] Executando entradas e posicionando Parciais e Trava 0x0...", flush=True)
    
    exchange.load_markets()
    
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
    except Exception as e:
        print(f"⚠️ Alerta ao definir alavancagem: {e}", flush=True)
    
    precio_atual = obter_preco_atual()
    qtd_moedas_raw = (CAPITAL_USDT * LEVERAGE) / precio_atual
    qtd_moedas = float(exchange.amount_to_precision(SYMBOL, qtd_moedas_raw))
    
    # 1. Abertura a Mercado em Hedge Mode
    ordem_long = exchange.create_market_buy_order(SYMBOL, qtd_moedas, {'positionSide': 'LONG'})
    ordem_short = exchange.create_market_sell_order(SYMBOL, qtd_moedas, {'positionSide': 'SHORT'})
    
    p_long = ordem_long.get('average') or precio_atual
    p_short = ordem_short.get('average') or precio_atual
    p_ref = (p_long + p_short) / 2.0
    
    print(f"✅ Entradas: Long {p_long} | Short {p_short} | Preço Ref: {p_ref:.6f}", flush=True)
    
    # 2. Cálculos dos Níveis de Preço
    preco_parcial = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - PARCIAL_PCT)))
    preco_0x0 = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - TRAVA_0X0_PCT)))
    preco_alvo = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - ALVO_FINAL_PCT)))
    
    qtd_parcial_short = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.85))
    qtd_parcial_long = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.30))
    qtd_total = float(exchange.amount_to_precision(SYMBOL, qtd_moedas))
    
    print(f"📌 Parcial em: {preco_parcial} | Trava 0x0 em: {preco_0x0} | Alvo em: {preco_alvo}", flush=True)
    
    # 3. Armar Parciais e Trava 0x0 Inicial na Binance
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qtd_parcial_short, None, {
        'positionSide': 'SHORT',
        'stopPrice': preco_parcial,
        'workingType': 'MARK_PRICE'
    })
    
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_parcial_long, None, {
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
    
    print("⏳ [FASE 1 OK] Posições armadas na Binance. Monitorando cotação em tempo real...", flush=True)
    
    # 4. MONITORAMENTO DE PREÇO DA FASE 1
    parcial_atingida = False
    
    while True:
        p_mercado = obter_preco_atual()
        if not p_mercado:
            time.sleep(3)
            continue
            
        # Posições encerradas na Trava 0x0 (Preço caiu abaixo do nível do 0x0)
        if p_mercado <= preco_0x0:
            print(f"🏁 Trava 0x0 atingida no preço! Cotação: {p_mercado:.6f} <= Gatilho: {preco_0x0:.6f}", flush=True)
            return
            
        # Detecta que o preço atingiu ou cruzou a Parcial
        if p_mercado <= preco_parcial:
            print(f"🎯 PARCIAL ATINGIDA NO PREÇO! Cotação: {p_mercado:.6f} <= Gatilho: {preco_parcial:.6f}", flush=True)
            parcial_atingida = True
            break
            
        time.sleep(3)
    
    # 5. FASE 2: Posicionar Alvo Final na Binance para a quantidade restante
    if parcial_atingida:
        print("🚀 [FASE 2] Posicionando ordens de Alvo Final no book da Binance...", flush=True)
        
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
            print("🛡️ [FASE 2 OK] Alvos finais armados no book!", flush=True)
        except Exception as e:
            print(f"⚠️ Alerta ao posicionar alvo final: {e}", flush=True)
            
        # Monitora a cotação até o encerramento total (Alvo ou Trava 0x0)
        while True:
            p_mercado = obter_preco_atual()
            if not p_mercado:
                time.sleep(3)
                continue
                
            if p_mercado <= preco_alvo or p_mercado <= preco_0x0:
                print(f"🏁 Operação finalizada! Cotação: {p_mercado:.6f}", flush=True)
                break
                
            time.sleep(3)

def loop_bot():
    print("🤖 Bot APEX iniciado na nuvem (Europa - Demo Trading)...", flush=True)
    while True:
        try:
            executar_ciclo()
            print(f"⏳ Operação concluída. Aguardando Cooldown de {COOLDOWN_SEGUNDOS/60} minutos para o próximo ciclo...\n", flush=True)
            time.sleep(COOLDOWN_SEGUNDOS)
        except Exception as e:
            print(f"⚠️ Erro no ciclo: {e}", flush=True)
            time.sleep(15)

if __name__ == '__main__':
    t = threading.Thread(target=loop_bot, daemon=True)
    t.start()
    run_flask()
