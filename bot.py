import ccxt
import time

# Configuração da API Testnet (Demo Binance)
exchange = ccxt.binance({
    'apiKey': '7lCdmhEJbzK6InKnU0O0AuSBQL5x1k4qNVqG2m9a6TtrnUrgP1BuEXD2MG7tkzVa',
    'secret': 'YfLMKP6GPATh3RhiCPhfwOXyAoy45zEWnOBmiyRoNUXPuux9Ir2PntqLtMhT2BWA',
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})
exchange.set_sandbox_mode(True)  # Ativa o ambiente de simulação / Demo

# Parâmetros Iniciais de Teste
SYMBOL = 'TUSDT'
LEVERAGE = 10
CAPITAL_USDT = 2.0         # $2 por lado ($20 notional)
PARCIAL_PCT = 0.0340       # 3.40% de queda (Alvo da Parcial 85/30)
TRAVA_0X0_PCT = 0.0576     # 5.76% de queda (Trava Zero Loss)
REPIQUE_PCT = 0.0172       # 1.72% de repique (Metade do caminho pós-parcial)
COOLDOWN_MINUTOS = 10      # Pausa de 10 minutos entre ciclos

def executar_ciclo():
    print("🚀 [PASSO 1] Iniciando novo ciclo automático...")
    
    # Configura alavancagem de 10x na Binance
    exchange.set_leverage(LEVERAGE, SYMBOL)
    
    # Lógica de cálculo do tamanho da posição (Notional)
    ticker = exchange.fetch_ticker(SYMBOL)
    precio_atual = ticker['last']
    quantidade_moedas = (CAPITAL_USDT * LEVERAGE) / precio_atual
    
    print(f"📊 Preço de Mercado Atual: {precio_atual} | Qtd Moedas: {quantidade_moedas:.2f}")

    # 1. Abertura Simultânea (Long + Short em Hedge Mode)
    print("⚡ Disparando ordens a mercado em Hedge Mode...")
    ordem_long = exchange.create_market_buy_order(SYMBOL, quantidade_moedas, {'positionSide': 'LONG'})
    ordem_short = exchange.create_market_sell_order(SYMBOL, quantidade_moedas, {'positionSide': 'SHORT'})
    
    # 2. Leitura dos Preços Reais de Execução (Cálculo Anti-Slippage)
    precio_long = ordem_long['average'] if ordem_long['average'] else precio_atual
    precio_short = ordem_short['average'] if ordem_short['average'] else precio_atual
    precio_ref = (precio_long + precio_short) / 2.0
    
    print(f"✅ Posições Abertas! Price Long: {precio_long} | Price Short: {precio_short}")
    print(f"🎯 Preço Referência Ponderado: {precio_ref:.6f}")
    
    # 3. Cálculo Dinâmico dos Pontos da Estratégia
    preco_parcial = precio_ref * (1.0 - PARCIAL_PCT)
    preco_0x0 = precio_ref * (1.0 - TRAVA_0X0_PCT)
    preco_repique = preco_parcial * (1.0 + REPIQUE_PCT)
    
    print(f"📌 [PASSO 2] Parcial (85/30) calculada para: {preco_parcial:.6f}")
    print(f"🛡️ [PASSO 2] Trava 0x0 Absoluto calculada para: {preco_0x0:.6f}")
    print(f"🎯 [PASSO 3] Target Repique calculado para: {preco_repique:.6f}")
    
    # Aqui o código envia as ordens condicionais para a Binance
    # ...
    
    print(f"⏳ [PASSO 4] Ciclo concluído. Aguardando {COOLDOWN_MINUTOS} minutos de Cooldown...\n")

if __name__ == '__main__':
    # Substitua pelas suas chaves nos campos acima
    print("🤖 Bot APEX iniciado e rodando em modo contínuo...")
    # executar_ciclo()
