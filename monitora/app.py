import streamlit as st
import pymysql
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

# Define o fuso horário oficial de Brasília (UTC-3)
FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="🖥️ Monitoramento",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="collapsed"  # Melhora a visualização inicial no celular
)

# CSS para otimização visual no Celular (Mobile Friendly)
st.markdown("""
    <style>
        /* Ajustes para telas pequenas (Celulares) */
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
            
            # Cálculo de diferença em segundos usando a referência do próprio banco
            delta_seconds = (db_now - ultima_att).total_seconds() if ultima_att else 999999

            if m_ativo == 0:
                status_calc = 'PAUSADO'
            elif delta_seconds > 75:
                status_calc = 'DESLIGADO'
            else:
                status_calc = status_banco

            # Conversão direta do registro UTC do banco para o Horário de Brasília
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

# --- FRAGMENTO COM AUTO-REFRESH A CADA 15 SEGUNDOS ---
@st.fragment(run_every="15s")
def renderizar_tabela_dashboard():
    df_lojas = buscar_dados_dashboard()
    
    col_t, col_r = st.columns([3, 1])
    with col_t:
        agora = datetime.now(FUSO_BRASILIA).strftime("%H:%M:%S")
        st.caption(f"⚡ Atualização automática ativa (Última: {agora} - Horário de Brasília)")
    with col_r:
        if st.button("🔄 Atualizar Agora", use_container_width=True):
            st.rerun()

    if not df_lojas.empty:
        def destacar_status(val):
            if val == 'ONLINE': return 'background-color: #162A16; color: #00FFB2'
            if val == 'OFFLINE': return 'background-color: #2A1616; color: #F75A68'
            if val == 'PAUSADO': return 'background-color: #16202A; color: #4CC4FF'
            if val == 'DESLIGADO': return 'background-color: #202024; color: #8D8D99'
            return ''

        st.dataframe(
            df_lojas.style.map(destacar_status, subset=['Status']),
            use_container_width=True,
            hide_index=True,
            height=500
        )
    else:
        st.info("Nenhuma loja encontrada.")

# --- INTERFACE WEB ---
st.title("🖥️ Monitoramento")

# Carrega dados iniciais apenas para popular a lista do menu
df_lojas_menu = buscar_dados_dashboard()
lojas_lista = df_lojas_menu["Nome da Loja"].tolist() if not df_lojas_menu.empty else []

# BARRA LATERAL (COMANDOS)
st.sidebar.header("🕹️ CONTROLE OPERACIONAL")
lojas_selecionadas = st.sidebar.multiselect("Selecione a(s) Loja(s):", lojas_lista)
desabilitar_botoes = len(lojas_selecionadas) == 0

st.sidebar.subheader("Comandos Remotos")

if st.sidebar.button("▶️ Iniciar Pedidos Web", disabled=desabilitar_botoes, use_container_width=True):
    executar_comando_remoto(lojas_selecionadas, "START")

# Botão de encerramento aciona o modal de senha
if st.sidebar.button("⏹️ Encerrar Pedidos Web", disabled=desabilitar_botoes, use_container_width=True):
    modal_confirmar_encerramento(lojas_selecionadas)

st.sidebar.markdown("---")

# PAUSAR / RETOMAR
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
    st.rerun()

# ABA PRINCIPAL DE NAVEGAÇÃO
tab_dash, tab_hist = st.tabs(["📊 Painel Geral", "📜 Logs"])

# ABA 1: DASHBOARD
with tab_dash:
    renderizar_tabela_dashboard()

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
