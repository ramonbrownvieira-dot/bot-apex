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

# Inicializa API com Variáveis de Ambiente
exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})
exchange.set_sandbox_mode(True)  # Demo Binance Testnet

SYMBOL = 'TUSDT'
LEVERAGE = 10
CAPITAL_USDT = 2.0         # $2 por lado
PARCIAL_PCT = 0.0340       # 3.40%
TRAVA_0X0_PCT = 0.0576     # 5.76%
COOLDOWN_SEGUNDOS = 600    # 10 minutos

def executar_operacao():
    print("🚀 [PASSO 1] Executando ordens reais na Binance Demo...")
    exchange.set_leverage(LEVERAGE, SYMBOL)
    
    ticker = exchange.fetch_ticker(SYMBOL)
    precio_atual = ticker['last']
    qtd_moedas = (CAPITAL_USDT * LEVERAGE) / precio_atual
    
    # 1. Abertura a Mercado em Hedge
    ordem_long = exchange.create_market_buy_order(SYMBOL, qtd_moedas, {'positionSide': 'LONG'})
    ordem_short = exchange.create_market_sell_order(SYMBOL, qtd_moedas, {'positionSide': 'SHORT'})
    
    # 2. Leitura do Slippage e Preço Médio Ponderado
    p_long = ordem_long['average'] if ordem_long['average'] else precio_atual
    p_short = ordem_short['average'] if ordem_short['average'] else precio_atual
    p_ref = (p_long + p_short) / 2.0
    
    print(f"✅ Entradas: Long {p_long} | Short {p_short} | Preço Ref: {p_ref:.6f}")
    
    # 3. Cálculos Dinâmicos
    preco_parcial = p_ref * (1.0 - PARCIAL_PCT)
    preco_0x0 = p_ref * (1.0 - TRAVA_0X0_PCT)
    
    qtd_parcial_short = qtd_moedas * 0.85
    qtd_parcial_long = qtd_moedas * 0.30
    
    print(f"📌 Posicionando Parcial em: {preco_parcial:.6f}")
    print(f"🛡️ Posicionando Trava 0x0 em: {preco_0x0:.6f}")
    
    # 4. Envio de Ordens Condicionais
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_parcial_short, None, {
        'positionSide': 'SHORT',
        'stopPrice': preco_parcial,
        'closePosition': False
    })
    
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_parcial_long, None, {
        'positionSide': 'LONG',
        'stopPrice': preco_parcial,
        'closePosition': False
    })
    
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qtd_moedas, None, {
        'positionSide': 'SHORT',
        'stopPrice': preco_0x0,
        'closePosition': True
    })
    exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qtd_moedas, None, {
        'positionSide': 'LONG',
        'stopPrice': preco_0x0,
        'closePosition': True
    })
    
    print("🛡️ Operação 100% armada e visível na Binance!")

def loop_bot():
    print("🤖 Bot APEX rodando na nuvem...")
    while True:
        try:
            executar_operacao()
            print(f"⏳ Aguardando {COOLDOWN_SEGUNDOS/60} minutos para o próximo ciclo...\n")
            time.sleep(COOLDOWN_SEGUNDOS)
        except Exception as e:
            print(f"⚠️ Erro no ciclo: {e}")
            time.sleep(30)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    loop_bot()
