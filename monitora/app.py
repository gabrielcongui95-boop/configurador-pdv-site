import streamlit as st
import streamlit.components.v1 as components
import pymysql
import pandas as pd
import time
from datetime import datetime
from zoneinfo import ZoneInfo

# Define o fuso horário oficial de Brasília (UTC-3)
FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CSS para otimização visual no Celular e Espaçamento Reduzido nos Botões
st.markdown("""
    <style>
        /* Reduz o espaçamento entre elementos e botões na barra lateral */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div {
            gap: 0.3rem !important;
        }
        [data-testid="stSidebar"] .stButton > button {
            width: 100% !important;
            margin-bottom: 2px !important;
        }
        
        /* Ajustes para telas pequenas (Celulares) */
        @media (max-width: 768px) {
            .stButton > button {
                width: 100% !important;
                height: 3em !important;
                font-size: 16px !important;
            }
            .block-container {
                padding-left: 0.8rem !important;
                padding-right: 0.8rem !important;
                padding-top: 1rem !important;
            }
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

            query = "SELECT nome_loja, rede, status, ultima_atualizacao, monitoramento_ativo, COALESCE(auto_restart, 0), comando FROM status_lojas ORDER BY nome_loja ASC"
            cursor.execute(query)
            dados = cursor.fetchall()
        
        lista_temp = []
        for row in dados:
            nome_loja, rede_nome, status_banco, ultima_att, m_ativo, a_restart, comando_banco = row
            
            delta_seconds = (db_now - ultima_att).total_seconds() if ultima_att else 999999

            if m_ativo == 0:
                status_calc = 'PAUSADO'
            elif delta_seconds > 75:
                status_calc = 'DESLIGADO'
            else:
                status_calc = status_banco

            if ultima_att:
                if ultima_att.tzinfo is None:
                    ultima_att_utc = ultima_att.replace(tzinfo=ZoneInfo("UTC"))
                else:
                    ultima_att_utc = ultima_att
                ultima_att_local = ultima_att_utc.astimezone(FUSO_BRASILIA).strftime('%d/%m/%Y %H:%M:%S')
            else:
                ultima_att_local = "-"

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

def reiniciar_lojas(lojas):
    # 1. Envia comando para encerrar/fechar o monitor
    executar_comando_remoto(lojas, "STOP")
    
    # 2. Aguarda 15 segundos exibindo alerta e spinner na tela
    st.toast("Comando STOP enviado! Aguardando 15 segundos para reabrir...", icon="⏳")
    with st.spinner("🔄 Encerrando o monitor... Aguardando 15 segundos para enviar o comando de reabrir (START)..."):
        time.sleep(15)
        
    # 3. Envia comando para iniciar/abrir o monitor novamente
    executar_comando_remoto(lojas, "START")

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

def alterar_auto_restart(lojas, ativar):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            format_strings = ', '.join(['%s'] * len(lojas))
            novo_auto_restart = 1 if ativar else 0
            cursor.execute(
                f"UPDATE status_lojas SET auto_restart = %s WHERE nome_loja IN ({format_strings})",
                (novo_auto_restart,) + tuple(lojas)
            )
        conn.commit()
        conn.close()
        st.toast("Auto reinício atualizado com sucesso!", icon="🔁")
    except Exception as e:
        st.error(f"Erro ao alterar auto reinício: {e}")

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

def buscar_historico(nome_loja, data_inicio=None, data_fim=None):
    try:
        conn = conectar_banco()
        with conn.cursor() as cursor:
            query = "SELECT status, data_evento FROM historico_status WHERE nome_loja = %s"
            params = [nome_loja]
            
            if data_inicio and data_fim:
                query += " AND DATE(data_evento) BETWEEN %s AND %s"
                params.extend([data_inicio, data_fim])
            elif data_inicio:
                query += " AND DATE(data_evento) >= %s"
                params.append(data_inicio)
            elif data_fim:
                query += " AND DATE(data_evento) <= %s"
                params.append(data_fim)
                
            query += " ORDER BY data_evento DESC"
            cursor.execute(query, tuple(params))
            res = cursor.fetchall()
        conn.close()

        dados_formatados = []
        for status, data_evento in res:
            if isinstance(data_evento, datetime):
                if data_evento.tzinfo is None:
                    data_evento = data_evento.replace(tzinfo=ZoneInfo("UTC"))
                data_br = data_evento.astimezone(FUSO_BRASILIA).strftime('%d/%m/%Y %H:%M:%S')
            else:
                data_br = data_evento
            dados_formatados.append({"Status": status, "Data/Hora": data_br})

        return pd.DataFrame(dados_formatados)
    except Exception as e:
        st.error(f"Erro ao buscar histórico: {e}")
        return pd.DataFrame()

# --- FRAGMENTO COM AUTO-REFRESH A CADA 15 SEGUNDOS ---
@st.fragment(run_every="15s")
def renderizar_tabela_dashboard():
    df_lojas = buscar_dados_dashboard()
    
    col_t, col_r = st.columns([3, 1])
    with col_t:
        agora = datetime.now(FUSO_BRASILIA).strftime("%H:%M:%S")
        st.caption(f"⚡ Atualização automática ativa (Última: {agora} - Brasília)")
    with col_r:
        if st.button("🔄 Atualizar Agora", use_container_width=True):
            st.rerun()

    termo_busca = st.text_input(
        "🔍 Filtrar por Rede ou Nome da Loja:", 
        placeholder="Digite para filtrar em tempo real...",
        key="campo_busca_lojas"
    )

    # JavaScript para forçar a busca a cada caractere digitado (sem precisar dar Enter)
    components.html(
        """
        <script>
        const doc = window.parent.document;
        const inputs = doc.querySelectorAll('div[data-testid="stTextInput"] input');
        inputs.forEach(input => {
            if (!input.dataset.liveSearch) {
                input.dataset.liveSearch = "true";
                input.addEventListener('input', () => {
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                });
            }
        });
        </script>
        """,
        height=0,
        width=0
    )

    if not df_lojas.empty:
        if termo_busca:
            df_exibicao = df_lojas[
                df_lojas["Nome da Loja"].astype(str).str.contains(termo_busca, case=False, na=False) |
                df_lojas["Rede"].astype(str).str.contains(termo_busca, case=False, na=False)
            ].reset_index(drop=True)
        else:
            df_exibicao = df_lojas.reset_index(drop=True)

        def destacar_status(val):
            if val == 'ONLINE': return 'background-color: #162A16; color: #00FFB2'
            if val == 'OFFLINE': return 'background-color: #2A1616; color: #F75A68'
            if val == 'PAUSADO': return 'background-color: #16202A; color: #4CC4FF'
            if val == 'DESLIGADO': return 'background-color: #202024; color: #8D8D99'
            return ''

        # Tabela interativa com seleção de linhas
        event = st.dataframe(
            df_exibicao.style.map(destacar_status, subset=['Status']),
            use_container_width=True,
            hide_index=True,
            height=500,
            on_select="rerun",
            selection_mode="multi-row",
            key="tabela_lojas"
        )

        # Captura as lojas marcadas nos checkboxes
        indices_selecionados = event.selection.rows
        if indices_selecionados:
            novas_selecionadas = df_exibicao.iloc[indices_selecionados]["Nome da Loja"].tolist()
        else:
            novas_selecionadas = []

        # Atualiza a seleção global e recarrega a barra lateral se houver alteração nos checkboxes
        if st.session_state.get("lojas_selecionadas") != novas_selecionadas:
            st.session_state["lojas_selecionadas"] = novas_selecionadas
            st.rerun()
    else:
        st.info("Nenhuma loja encontrada.")

# --- INTERFACE WEB ---
st.title("🖥️ Monitoramento")

# Inicializa o estado global das lojas selecionadas
if "lojas_selecionadas" not in st.session_state:
    st.session_state["lojas_selecionadas"] = []

lojas_selecionadas = st.session_state["lojas_selecionadas"]
desabilitar_botoes = len(lojas_selecionadas) == 0

# BARRA LATERAL (COMANDOS)
st.sidebar.header("🕹️ PAINEL OPERACIONAL")

if lojas_selecionadas:
    st.sidebar.success(f"📌 {len(lojas_selecionadas)} loja(s) selecionada(s)")
else:
    st.sidebar.info("Selecione para enviar comandos.")

st.sidebar.subheader("Comandos Remotos")

if st.sidebar.button("▶️ Iniciar Pedidos Web", disabled=desabilitar_botoes, use_container_width=True):
    executar_comando_remoto(lojas_selecionadas, "START")

if st.sidebar.button("🔄 Reiniciar Pedidos Web", disabled=desabilitar_botoes, use_container_width=True):
    reiniciar_lojas(lojas_selecionadas)

st.sidebar.markdown("---")

# PAUSAR / RETOMAR
st.sidebar.subheader("Monitoramento")
col_p1, col_p2 = st.sidebar.columns(2)
with col_p1:
    if st.button("⏸️ Pausar", disabled=desabilitar_botoes, use_container_width=True):
        alterar_pausa(lojas_selecionadas, True)
with col_p2:
    if st.button("▶️ Retomar", disabled=desabilitar_botoes, use_container_width=True):
        alterar_pausa(lojas_selecionadas, False)

st.sidebar.markdown("---")

# AUTO REINÍCIO (ATIVAR / DESATIVAR)
st.sidebar.subheader("🔁 Auto Reinício")
col_ar1, col_ar2 = st.sidebar.columns(2)
with col_ar1:
    if st.button("✅ Ativar", disabled=desabilitar_botoes, use_container_width=True, key="btn_ar_ativar"):
        alterar_auto_restart(lojas_selecionadas, True)
with col_ar2:
    if st.button("❌ Desativar", disabled=desabilitar_botoes, use_container_width=True, key="btn_ar_desativar"):
        alterar_auto_restart(lojas_selecionadas, False)

st.sidebar.markdown("---")

if st.sidebar.button("🗑️ Remover Monitor (Uninstall)", disabled=desabilitar_botoes, use_container_width=True):
    executar_comando_remoto(lojas_selecionadas, "UNINSTALL")

if st.sidebar.button("🚨 Apagar Lojas do Banco", disabled=desabilitar_botoes, type="primary", use_container_width=True):
    excluir_lojas(lojas_selecionadas)
    st.session_state["lojas_selecionadas"] = []
    st.rerun()

# ABA PRINCIPAL DE NAVEGAÇÃO
tab_dash, tab_hist = st.tabs(["📊 Painel Geral", "📜 Logs"])

# ABA 1: DASHBOARD
with tab_dash:
    renderizar_tabela_dashboard()

# ABA 2: HISTÓRICO
with tab_hist:
    st.subheader("Histórico por Loja")
    
    df_lojas_menu = buscar_dados_dashboard()
    lojas_lista = df_lojas_menu["Nome da Loja"].tolist() if not df_lojas_menu.empty else []

    col_h1, col_h2 = st.columns([1, 1])
    with col_h1:
        loja_hist_sel = st.selectbox("Escolha a loja para ver o histórico:", lojas_lista)
    with col_h2:
        periodo = st.date_input("Filtrar por período (Início e Fim):", value=(), format="DD/MM/YYYY")

    data_ini = periodo[0] if len(periodo) > 0 else None
    data_fim = periodo[1] if len(periodo) > 1 else None

    if loja_hist_sel:
        df_hist = buscar_historico(loja_hist_sel, data_ini, data_fim)
        if not df_hist.empty:
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
        else:
            st.warning("Nenhum histórico encontrado para o filtro selecionado.")
