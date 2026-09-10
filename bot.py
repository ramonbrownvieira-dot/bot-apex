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
ALVO_FINAL_PCT = 0.0800    # Exemplo: 8.00% para o alvo final pós-parcial
COOLDOWN_SEGUNDOS = 600    # 10 minutos

def obter_quantidade_posicoes():
    """Retorna as quantidades atuais das posições [Long, Short]."""
    long_qty, short_qty = 0.0, 0.0
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for pos in positions:
            side = pos.get('side') or pos.get('info', {}).get('positionSide')
            contracts = float(pos.get('contracts', 0) or 0)
            if pos['symbol'] == SYMBOL:
                if side == 'LONG' or pos.get('positionSide') == 'LONG':
                    long_qty = contracts
                elif side == 'SHORT' or pos.get('positionSide') == 'SHORT':
                    short_qty = contracts
    except Exception as e:
        print(f"⚠️ Erro ao consultar posições: {e}", flush=True)
    return long_qty, short_qty

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
    
    print("⏳ [FASE 1 OK] Aguardando o mercado atingir a Parcial...", flush=True)
    
    # Aguarda a confirmação de que as posições foram computadas na API
    time.sleep(5)
    
    # 4. LOOP DE MONITORAMENTO DA FASE 1 (Aguardando Parcial)
    parcial_executada = False
    while True:
        l_qty, s_qty = obter_quantidade_posicoes()
        
        # Se ambas fecharam antes da parcial (ex: bateram na trava 0x0 direta)
        if l_qty == 0 and s_qty == 0:
            print("🏁 Posições encerradas na Trava 0x0 antes da Parcial.", flush=True)
            return
            
        # Detecta que a parcial foi executada (quantidade diminuiu)
        if (s_qty < qtd_total or l_qty < qtd_total) and (l_qty > 0 or s_qty > 0):
            print("🎯 PARCIAL EXECUTADA COM SUCESSO!", flush=True)
            parcial_executada = True
            break
            
        time.sleep(5)
    
    # 5. FASE 2: Posicionar Ordens de Alvo Final Pós-Parcial
    if parcial_executada:
        print("🚀 [FASE 2] Posicionando ordens de Alvo Final e mantendo Trava 0x0...", flush=True)
        
        l_restante, s_restante = obter_quantidade_posicoes()
        
        if s_restante > 0:
            exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', s_restante, None, {
                'positionSide': 'SHORT',
                'stopPrice': preco_alvo,
                'workingType': 'MARK_PRICE'
            })
        if l_restante > 0:
            exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', l_restante, None, {
                'positionSide': 'LONG',
                'stopPrice': preco_alvo,
                'workingType': 'MARK_PRICE'
            })
            
        print("🛡️ [FASE 2 OK] Alvos armados! Aguardando finalização do ciclo...", flush=True)
        
        # Monitora até o encerramento total
        while True:
            l_qty, s_qty = obter_quantidade_posicoes()
            if l_qty == 0 and s_qty == 0:
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
