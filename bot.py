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
COOLDOWN_SEGUNDOS = 600    # 10 minutos (após fechamento total)

def tem_posicoes_ativas():
    """Retorna True se houver posição Long ou Short aberta para o símbolo."""
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for pos in positions:
            contracts = float(pos.get('contracts', 0) or 0)
            if pos['symbol'] == SYMBOL and contracts > 0:
                return True
    except Exception as e:
        print(f"⚠️ Erro ao verificar posições: {e}", flush=True)
    return False

def executar_operacao():
    print("🚀 [PASSO 1] Executando ordens reais na Binance Demo...", flush=True)
    
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
    
    # 2. Leitura do Preço Médio Ponderado ($P_{ref}$)
    p_long = ordem_long.get('average') or precio_atual
    p_short = ordem_short.get('average') or precio_atual
    p_ref = (p_long + p_short) / 2.0
    
    print(f"✅ Entradas: Long {p_long} | Short {p_short} | Preço Ref: {p_ref:.6f}", flush=True)
    
    # 3. Cálculos Dinâmicos com Precisão Nativa do Par
    preco_parcial = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - PARCIAL_PCT)))
    preco_0x0 = float(exchange.price_to_precision(SYMBOL, p_ref * (1.0 - TRAVA_0X0_PCT)))
    
    qtd_parcial_short = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.85))
    qtd_parcial_long = float(exchange.amount_to_precision(SYMBOL, qtd_moedas * 0.30))
    qtd_total = float(exchange.amount_to_precision(SYMBOL, qtd_moedas))
    
    print(f"📌 Posicionando Parcial em: {preco_parcial}", flush=True)
    print(f"🛡️ Posicionando Trava 0x0 em: {preco_0x0}", flush=True)
    
    # 4. PARCIAIS (TAKE_PROFIT_MARKET / STOP_MARKET)
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
    
    # 5. TRAVA 0x0 (Fechamento total condicional)
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
    
    print("🛡️ Operação 100% armada! Iniciando monitoramento da posição...", flush=True)

def loop_bot():
    print("🤖 Bot APEX iniciado na nuvem (Europa - Demo Trading)...", flush=True)
    while True:
        try:
            # 1. Se não houver posições abertas, abre novo ciclo
            if not tem_posicoes_ativas():
                executar_operacao()
            
            # 2. Aguarda e monitora até todas as posições serem totalmente fechadas
            while tem_posicoes_ativas():
                time.sleep(5)
            
            # 3. Posições zeradas -> Aplica o Cooldown de 10 minutos
            print("🏁 Todas as posições do ciclo foram encerradas!", flush=True)
            print(f"⏳ Iniciando Cooldown de {COOLDOWN_SEGUNDOS/60} minutos para a próxima operação...\n", flush=True)
            time.sleep(COOLDOWN_SEGUNDOS)
            
        except Exception as e:
            print(f"⚠️ Erro no ciclo: {e}", flush=True)
            time.sleep(10)

if __name__ == '__main__':
    t = threading.Thread(target=loop_bot, daemon=True)
    t.start()
    run_flask()
