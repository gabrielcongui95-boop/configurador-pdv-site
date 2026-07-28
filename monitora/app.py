import streamlit as st
import pymysql
import pandas as pd
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Painel de Monitoramento",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Estilização CSS personalizada para Celulares e Cards
st.markdown("""
    <style>
        /* Otimizações Mobile */
        @media (max-width: 768px) {
            .stButton > button {
                width: 100% !important;
                height: 3em !important;
                font-size: 16px !important;
                margin-bottom: 5px;
            }
            .block-container {
                padding-left: 0.8rem !important;
                padding-right: 0.8rem !important;
                padding-top: 1rem !important;
            }
        }
        /* Ajuste visual dos cards */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 10px !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            background-color: #1A1D24;
        }
    </style>
""", unsafe_allow_html=True)

# --- CONFIGURAÇÃO DO BANCO ---
DB_HOST = st.secrets.get("DB_HOST", "mysql-71db31c-gabriel-8279.g.aivencloud.com")
DB_PORT = int(st.secrets.get("DB_PORT", 14801))
DB_USER = st.secrets.get("DB_USER", "avnadmin")
DB_PASS = st.secrets.get("DB_PASS", "AVNS_krbCrutmFqF_LkqTrsa")
DB_NAME = st.secrets.get("DB_NAME", "monitoramento_pdv")

def conectar_banco():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME,
        ssl={'ssl': True}, connect_timeout=5
    )

# --- FUNÇÕES DE BANCO ---
def buscar_dados_dashboard():
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            cursor.execute("SELECT NOW()")
            db_now = cursor.fetchone()[0]
            local_now = datetime.now()
            ajuste_fuso = local_now - db_now

            query = "SELECT nome_loja, rede, status, ultima_atualizacao, monitoramento_ativo, COALESCE(auto_restart, 0), comando FROM status_lojas ORDER BY nome_loja ASC"
            cursor.execute(query)
            dados = cursor.fetchall()
        
        lista_temp = []
        for row in dados:
            nome_loja, rede_nome, status_banco, ultima_att, m_ativo, a_restart, comando_banco = row
            delta_seconds = (db_now - ultima_att).total_seconds()

            if m_ativo == 0:
                status_calc = 'PAUSADO'
            elif delta_seconds > 75:
                status_calc = 'DESLIGADO'
            else:
                status_calc = status_banco

            ultima_att_local = (ultima_att + ajuste_fuso).strftime('%d/%m/%Y %H:%M:%S')
            
            lista_temp.append({
                "Nome da Loja": nome_loja,
                "Rede": rede_nome,
                "Status": status_calc,
                "Auto Reinício": "✅ SIM" if a_restart == 1 else "❌ NÃO",
                "Última Atualização": ultima_att_local,
                "Comando Pendente": comando_banco or "-"
            })
        
        conn.close()
        return pd.DataFrame(lista_temp)
    except Exception as e:
        st.error(f"Erro ao conectar ao banco de dados: {e}")
        return pd.DataFrame()

def executar_comando_remoto(lojas, comando):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            format_strings = ', '.join(['%s'] * len(lojas))
            cursor.execute(f"UPDATE status_lojas SET comando = %s WHERE nome_loja IN ({format_strings})", (comando,) + tuple(lojas))
        conn.commit()
        conn.close()
        st.toast(f"Comando '{comando}' enviado para {len(lojas)} loja(s)!", icon="🚀")
    except Exception as e:
        st.error(f"Erro ao enviar comando: {e}")

def alterar_pausa(lojas, pausar):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            format_strings = ', '.join(['%s'] * len(lojas))
            novo_m_ativo = 0 if pausar else 1
            novo_status = 'PAUSADO' if pausar else 'ONLINE'
            
            cursor.execute(f"UPDATE status_lojas SET monitoramento_ativo = %s, status = %s, ultima_atualizacao = NOW() WHERE nome_loja IN ({format_strings})", (novo_m_ativo, novo_status) + tuple(lojas))
        conn.commit()
        conn.close()
        st.toast("Status de monitoramento atualizado!", icon="🔄")
    except Exception as e:
        st.error(f"Erro na alteração de pausa: {e}")

def excluir_lojas(lojas):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            format_strings = ', '.join(['%s'] * len(lojas))
            cursor.execute(f"DELETE FROM historico_status WHERE nome_loja IN ({format_strings})", tuple(lojas))
            cursor.execute(f"DELETE FROM status_lojas WHERE nome_loja IN ({format_strings})", tuple(lojas))
        conn.commit()
        conn.close()
        st.toast("Lojas removidas com sucesso!", icon="🗑️")
    except Exception as e:
        st.error(f"Erro ao excluir lojas: {e}")

def buscar_historico(nome_loja):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT status, data_evento 
                FROM historico_status 
                WHERE nome_loja = %s 
                ORDER BY data_evento DESC
            """, (nome_loja,))
            res = cursor.fetchall()
        conn.close()
        return pd.DataFrame(res, columns=["Status", "Data/Hora"])
    except Exception as e:
        st.error(f"Erro ao buscar histórico: {e}")
        return pd.DataFrame()

# --- MODAL DE SEGURANÇA PARA ENCERRAMENTO ---
@st.dialog("🔒 Autenticação de Segurança")
def modal_confirmar_encerramento(lojas):
    st.warning(f"Você está prestes a encerrar os pedidos WEB para **{len(lojas)} loja(s)**.")
    senha = st.text_input("Digite a senha de confirmação:", type="password")
    
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        if st.button("Confirmar", type="primary", use_container_width=True):
            if senha == "080613":
                executar_comando_remoto(lojas, "STOP")
                st.rerun()
            else:
                st.error("Senha incorreta!")
    with col_c2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()

# --- FRAGMENTO DE CARDS COM FILTROS E REFRESH AUTOMÁTICO ---
@st.fragment(run_every="15s")
def renderizar_cards_dashboard():
    df_lojas = buscar_dados_dashboard()

    # --- BARRA DE FILTROS NA TELA PRINCIPAL ---
    col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
    
    with col_f1:
        busca_nome = st.text_input("🔍 Buscar Loja:", placeholder="Digite o nome da loja...")
    
    with col_f2:
        redes_disponiveis = ["Todas"] + (sorted(df_lojas["Rede"].dropna().unique().tolist()) if not df_lojas.empty else [])
        rede_selecionada = st.selectbox("🏷️ Filtrar por Rede:", redes_disponiveis)
        
    with col_f3:
        st.write("")
        st.write("")
        if st.button("🔄 Atualizar", use_container_width=True):
            st.rerun()

    # Aplicando filtros
    df_filtrado = df_lojas.copy()
    if not df_filtrado.empty:
        if busca_nome:
            df_filtrado = df_filtrado[df_filtrado["Nome da Loja"].str.contains(busca_nome, case=False, na=False)]
        if rede_selecionada != "Todas":
            df_filtrado = df_filtrado[df_filtrado["Rede"] == rede_selecionada]

    agora = datetime.now().strftime("%H:%M:%S")
    st.caption(f"⚡ Atualização automática a cada 15s (Última: {agora}) — **{len(df_filtrado)}** loja(s) encontrada(s)")

    st.markdown("---")

    # --- EXIBIÇÃO DAS LOJAS EM CARDS ---
    if not df_filtrado.empty:
        # Cria uma grade de 2 colunas para os cards
        cols = st.columns(2)
        
        for idx, row in df_filtrado.reset_index(drop=True).iterrows():
            col_target = cols[idx % 2]
            
            with col_target:
                with st.container(border=True):
                    # Definir a cor do status
                    status_val = row["Status"]
                    if status_val == 'ONLINE':
                        badge_color = "#00FFB2"
                        badge_text = "🟢 ONLINE"
                    elif status_val == 'OFFLINE':
                        badge_color = "#F75A68"
                        badge_text = "🔴 OFFLINE"
                    elif status_val == 'PAUSADO':
                        badge_color = "#4CC4FF"
                        badge_text = "🔵 PAUSADO"
                    else:
                        badge_color = "#8D8D99"
                        badge_text = "⚪ DESLIGADO"

                    # Cabeçalho do Card
                    c_h1, c_h2 = st.columns([3, 2])
                    with c_h1:
                        st.subheader(f"🏪 {row['Nome da Loja']}")
                        st.caption(f"Rede: **{row['Rede']}**")
                    with c_h2:
                        st.markdown(
                            f"<div style='text-align: right; font-weight: bold; color: {badge_color}; font-size: 1.1rem; padding-top: 5px;'>"
                            f"{badge_text}</div>", 
                            unsafe_allow_html=True
                        )

                    st.markdown("<hr style='margin: 8px 0; opacity: 0.2;'>", unsafe_allow_html=True)

                    # Detalhes do Card
                    c_d1, c_d2 = st.columns(2)
                    with c_d1:
                        st.markdown(f"**Auto Reinício:** {row['Auto Reinício']}")
                        st.markdown(f"**Comando Pendente:** `{row['Comando Pendente']}`")
                    with c_d2:
                        st.markdown("**Última Atualização:**")
                        st.caption(f"🕒 {row['Última Atualização']}")
    else:
        st.info("Nenhuma loja encontrada com os filtros informados.")

# --- INTERFACE WEB ---
st.title("Painel de Monitoramento")

# Busca inicial para popular seletores
df_lojas_menu = buscar_dados_dashboard()
lojas_lista = df_lojas_menu["Nome da Loja"].tolist() if not df_lojas_menu.empty else []

# BARRA LATERAL (COMANDOS OPERACIONAIS)
st.sidebar.header("🕹️ CONTROLE OPERACIONAL")
lojas_selecionadas = st.sidebar.multiselect("Selecione a(s) Loja(s):", lojas_lista)
desabilitar_botoes = len(lojas_selecionadas) == 0

st.sidebar.subheader("Comandos Remotos")

if st.sidebar.button("▶️ Iniciar Pedidos Web", disabled=desabilitar_botoes, use_container_width=True):
    executar_comando_remoto(lojas_selecionadas, "START")

if st.sidebar.button("⏹️ Encerrar Pedidos Web", disabled=desabilitar_botoes, use_container_width=True):
    modal_confirmar_encerramento(lojas_selecionadas)

st.sidebar.markdown("---")

col_p1, col_p2 = st.sidebar.columns(2)
with col_p1:
    if st.button("⏸️ Pausar", disabled=desabilitar_botoes, use_container_width=True):
        alterar_pausa(lojas_selecionadas, True)
with col_p2:
    if st.button("▶️ Retomar", disabled=desabilitar_botoes, use_container_width=True):
        alterar_pausa(lojas_selecionadas, False)

st.sidebar.markdown("---")

if st.sidebar.button("🗑️ Remover Monitor (Uninstall)", disabled=desabilitar_botoes, use_container_width=True):
    executar_comando_remoto(lojas_selecionadas, "UNINSTALL")

if st.sidebar.button("🚨 Apagar Lojas do Banco", disabled=desabilitar_botoes, type="primary", use_container_width=True):
    excluir_lojas(lojas_selecionadas)
    st.rerun()

# ABA PRINCIPAL DE NAVEGAÇÃO
tab_dash, tab_hist = st.tabs(["📊 Painel Geral", "📜 Logs"])

# ABA 1: DASHBOARD EM CARDS
with tab_dash:
    renderizar_cards_dashboard()

# ABA 2: HISTÓRICO
with tab_hist:
    st.subheader("Histórico por Loja")
    loja_hist_sel = st.selectbox("Escolha a loja para ver o histórico:", lojas_lista)
    
    if loja_hist_sel:
        df_hist = buscar_historico(loja_hist_sel)
        if not df_hist.empty:
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
        else:
            st.warning("Nenhum histórico encontrado para esta loja.")
