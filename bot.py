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
CAPITAL_USDT = 2.0         # Pode ser alterado para qualquer valor (ex: 10, 50, 100)
PARCIAL_PCT = 0.0340       # 3.40%
TRAVA_0X0_PCT = 0.0576     # 5.76%
ALVO_FINAL_PCT = 0.0800    # 8.00%
COOLDOWN_SEGUNDOS = 600    # 10 minutos (após fechamento total)

def obter_margens_posicoes():
    """Lê a margem alocada nas posições Long e Short."""
    margin_long, margin_short = 0.0, 0.0
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for pos in positions:
            if pos['symbol'] == SYMBOL:
                side = pos.get('side') or pos.get('info', {}).get('positionSide')
                initial_margin = float(pos.get('initialMargin', 0) or pos.get('info', {}).get('positionInitialMargin', 0) or 0)
                
                if initial_margin == 0:
                    notional = abs(float(pos.get('notional', 0) or pos.get('info', {}).get('notional', 0) or 0))
                    initial_margin = notional / LEVERAGE
                
                if side == 'LONG' or pos.get('positionSide') == 'LONG':
                    margin_long = initial_margin
                elif side == 'SHORT' or pos.get('positionSide') == 'SHORT':
                    margin_short = initial_margin
    except Exception as e:
        print(f"⚠️ Erro ao consultar margens: {e}", flush=True)
    return margin_long, margin_short

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
    
    print("⏳ [FASE 1 OK] Posições armadas. Aguardando estabilização do cache da API...", flush=True)
    
    # Aguarda o cache registrar a margem na API
    time.sleep(30)
    
    # Captura a margem inicial combinada de referência
    m_long_ini, m_short_ini = obter_margens_posicoes()
    margem_inicial_total = m_long_ini + m_short_ini
    
    # Prevenção caso o retorno de margem venha zerado por instabilidade da API
    if margem_inicial_total <= 0:
        margem_inicial_total = CAPITAL_USDT * 2.0
        
    print(f"👀 [MONITORAMENTO] Margem Inicial Registrada: ${margem_inicial_total:.2f}. Monitorando percentuais...", flush=True)
    
    # 4. MONITORAMENTO PERCENTUAL DA FASE 1
    parcial_detectada = False
    confirmacoes_zerado = 0
    
    while True:
        m_long, m_short = obter_margens_posicoes()
        margem_atual_total = m_long + m_short
        
        # Posição zerada: Margem atual representa menos de 2% da margem inicial
        if margem_atual_total <= (margem_inicial_total * 0.02):
            confirmacoes_zerado += 1
            if confirmacoes_zerado >= 3:
                print(f"🏁 Margem Zerada (Atual: ${margem_atual_total:.2f} / Inicial: ${margem_inicial_total:.2f}). Trava 0x0 executada antes da Parcial.", flush=True)
                return
        else:
            confirmacoes_zerado = 0
            
            # Cálculo do desequilíbrio entre as pontas Long e Short
            diferenca_relativa = abs(m_long - m_short) / max((m_long + m_short), 0.001)
            
            # Detecta parcial se:
            # 1. A margem total caiu para menos de 75% da margem inicial OU
            # 2. O desequilíbrio entre as pontas Long e Short for maior que 25%
            if (margem_atual_total <= (margem_inicial_total * 0.75)) or (diferenca_relativa >= 0.25):
                print(f"🎯 PARCIAL EXECUTADA! Margem Atual: ${margem_atual_total:.2f} (Inicial: ${margem_inicial_total:.2f} | Desequilíbrio: {diferenca_relativa*100:.1f}%)", flush=True)
                parcial_detectada = True
                break
                
        time.sleep(5)
    
    # 5. FASE 2: Posicionar Alvo Final para qualquer valor de capital
    if parcial_detectada:
        print("🚀 [FASE 2] Posicionando ordens de Alvo Final na Binance...", flush=True)
        
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
            
        # Monitora até o encerramento total da margem
        confirmacoes_zerado = 0
        while True:
            m_long, m_short = obter_margens_posicoes()
            if (m_long + m_short) <= (margem_inicial_total * 0.02):
                confirmacoes_zerado += 1
                if confirmacoes_zerado >= 3:
                    print("🏁 Operação 100% finalizada com Alvo! Margem zerada.", flush=True)
                    break
            else:
                confirmacoes_zerado = 0
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
