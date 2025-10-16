import streamlit as st
import pandas as pd
import psycopg2 
from datetime import datetime
from io import BytesIO
import base64
import os
import hashlib
import time
import uuid

# ==============================================================================
# 1. CONFIGURAÇÃO DE CONEXÃO SEGURA
# ==============================================================================

def get_connection_config():
    """Obtém configuração de conexão de forma segura"""
    config = {
        'host': None,
        'database': None,
        'user': None,
        'password': None,
        'port': 5432
    }
    
    # Tenta via st.secrets (desenvolvimento local)
    try:
        if 'postgres' in st.secrets:
            config['host'] = st.secrets.postgres.host
            config['database'] = st.secrets.postgres.database
            config['user'] = st.secrets.postgres.user
            config['password'] = st.secrets.postgres.password
            config['port'] = st.secrets.postgres.get('port', 5432)
            return config, "local"
    except:
        pass
    
    # Tenta variáveis de ambiente (produção)
    config['host'] = os.environ.get('PGHOST')
    config['database'] = os.environ.get('PGDATABASE') 
    config['user'] = os.environ.get('PGUSER')
    config['password'] = os.environ.get('PGPASSWORD')
    
    if all([config['host'], config['database'], config['user'], config['password']]):
        return config, "environment"
    
    return None, "none"

@st.cache_resource
def init_connection():
    """Inicializa conexão com Neon DB"""
    config, source = get_connection_config()
    if not config:
        return None
        
    try:
        # Conexão usando st.connection
        conn = st.connection("postgres", type="sql")
        
        # Testa a conexão
        with conn.session as s:
            s.execute("SELECT 1")
            
        st.sidebar.success(f"✅ Conectado ao Neon DB (via {source})")
        return conn
        
    except Exception as e:
        st.sidebar.error(f"❌ Erro na conexão: {e}")
        return None

def get_db_cursor():
    """Retorna cursor para operações DML/DDL"""
    try:
        if conn is None:
            return None, None
            
        conn_obj = conn.session
        cursor_obj = conn_obj.cursor()
        return conn_obj, cursor_obj
        
    except Exception as e:
        st.error(f"Erro ao obter cursor: {e}")
        return None, None

# ==============================================================================
# 2. INICIALIZAÇÃO DO BANCO DE DADOS
# ==============================================================================

def hash_password(password):
    """Hash de senha usando SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    """Inicialização do banco de dados"""
    if st.session_state.get('db_initialized', False):
        return
        
    conn_temp, c = get_db_cursor()
    if c is None:
        st.error("Não foi possível inicializar o banco de dados")
        return
        
    try:
        # Tabela de usuários
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY, 
                username TEXT UNIQUE, 
                password TEXT, 
                role TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabela de respostas HPO
        c.execute('''
            CREATE TABLE IF NOT EXISTS responses (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                a1 INTEGER, a2 INTEGER, b1 INTEGER, b2 INTEGER,
                c1 INTEGER, c2 INTEGER, d1 INTEGER, d2 INTEGER,
                e1 INTEGER, e2 INTEGER, f1 INTEGER, f2 INTEGER,
                g1 INTEGER, g2 INTEGER,
                comentario TEXT,
                session_id TEXT
            )
        ''')
        
        # Tabela de respostas de Liderança
        c.execute('''
            CREATE TABLE IF NOT EXISTS lideranca_responses (
                id SERIAL PRIMARY KEY,
                session_id TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                question_id TEXT,
                response TEXT,
                response_time REAL
            )
        ''')
        
        # Usuários padrão
        default_users = [
            ('admin', hash_password('admin123'), 'administrador'),
            ('gestor', hash_password('gestor123'), 'gestor')
        ]
        
        for username, password, role in default_users:
            c.execute('''
                INSERT INTO users (username, password, role) 
                VALUES (%s, %s, %s) 
                ON CONFLICT (username) DO NOTHING
            ''', (username, password, role))
        
        conn_temp.commit()
        st.session_state.db_initialized = True
        st.sidebar.success("✅ Banco de dados inicializado!")
        
    except Exception as e:
        st.error(f"❌ Erro na inicialização do banco: {e}")
        conn_temp.rollback()
    finally:
        if c:
            c.close()

# ==============================================================================
# 3. FUNÇÕES CRUD
# ==============================================================================

def check_login(username, password):
    """Verifica credenciais de login"""
    try:
        hashed_password = hash_password(password)
        query = "SELECT id, username, role FROM users WHERE username = %s AND password = %s"
        
        conn_temp, c = get_db_cursor()
        if c is None:
            return None
            
        c.execute(query, (username, hashed_password))
        result = c.fetchone()
        
        if result:
            user_data = {
                'id': result[0],
                'username': result[1], 
                'role': result[2]
            }
            c.close()
            return user_data
            
        c.close()
        return None
        
    except Exception as e:
        st.error(f"Erro no login: {e}")
        return None

def add_user(username, password, role):
    """Adiciona novo usuário"""
    conn_temp, c = get_db_cursor()
    if c is None:
        return False
        
    try:
        hashed_password = hash_password(password)
        c.execute('''
            INSERT INTO users (username, password, role) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (username) DO NOTHING
        ''', (username, hashed_password, role))
        
        conn_temp.commit()
        success = c.rowcount > 0
        return success
        
    except Exception as e:
        st.error(f"Erro ao adicionar usuário: {e}")
        conn_temp.rollback()
        return False
    finally:
        if c:
            c.close()

def list_users():
    """Lista todos os usuários"""
    try:
        return conn.query("SELECT id, username, role, created_at FROM users ORDER BY created_at DESC")
    except Exception as e:
        st.error(f"Erro ao listar usuários: {e}")
        return pd.DataFrame()

def delete_user(user_id):
    """Exclui usuário"""
    conn_temp, c = get_db_cursor()
    if c is None:
        return False
        
    try:
        c.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn_temp.commit()
        return True
    except Exception as e:
        st.error(f"Erro ao excluir usuário: {e}")
        conn_temp.rollback()
        return False
    finally:
        if c:
            c.close()

@st.cache_data(ttl=300)
def load_hpo_responses():
    """Carrega respostas HPO"""
    try:
        df = conn.query("SELECT * FROM responses ORDER BY timestamp DESC")
        if 'comentario' not in df.columns:
            df['comentario'] = ''
        return df
    except Exception as e:
        st.error(f"Erro ao carregar dados HPO: {e}")
        return pd.DataFrame()

def save_hpo_response(responses, comentario=""):
    """Salva resposta HPO"""
    conn_temp, c = get_db_cursor()
    if c is None:
        return False
        
    try:
        session_id = str(uuid.uuid4())
        
        c.execute('''
            INSERT INTO responses 
            (a1, a2, b1, b2, c1, c2, d1, d2, e1, e2, f1, f2, g1, g2, comentario, session_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', tuple(responses) + (comentario, session_id))
        
        conn_temp.commit()
        load_hpo_responses.clear()
        return True
        
    except Exception as e:
        st.error(f"Erro ao salvar resposta HPO: {e}")
        conn_temp.rollback()
        return False
    finally:
        if c:
            c.close()

@st.cache_data(ttl=300)
def load_lideranca_responses():
    """Carrega respostas de Liderança"""
    try:
        df = conn.query("SELECT * FROM lideranca_responses ORDER BY timestamp DESC")
        return df
    except Exception as e:
        st.error(f"Erro ao carregar dados de Liderança: {e}")
        return pd.DataFrame()

def save_lideranca_response(question_data):
    """Salva resposta de Liderança"""
    conn_temp, c = get_db_cursor()
    if c is None:
        return False
        
    try:
        session_id = str(uuid.uuid4())
        
        for i, (question_id, response, response_time) in enumerate(question_data, 1):
            c.execute('''
                INSERT INTO lideranca_responses 
                (session_id, question_id, response, response_time)
                VALUES (%s, %s, %s, %s)
            ''', (session_id, f"q{i}", response, response_time))
        
        conn_temp.commit()
        load_lideranca_responses.clear()
        return True
        
    except Exception as e:
        st.error(f"Erro ao salvar resposta de Liderança: {e}")
        conn_temp.rollback()
        return False
    finally:
        if c:
            c.close()

def delete_all_responses():
    """Apaga todas as respostas"""
    conn_temp, c = get_db_cursor()
    if c is None:
        return False
        
    try:
        c.execute("DELETE FROM responses")
        c.execute("DELETE FROM lideranca_responses")
        conn_temp.commit()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Erro ao apagar respostas: {e}")
        conn_temp.rollback()
        return False
    finally:
        if c:
            c.close()

# ==============================================================================
# 4. FUNÇÕES DE CÁLCULO E ANÁLISE
# ==============================================================================

def calculate_hpo_stats(df):
    """Calcula estatísticas do questionário HPO"""
    if df.empty:
        return {}
    
    domains = {
        'A': ['a1', 'a2'], 'B': ['b1', 'b2'], 'C': ['c1', 'c2'], 
        'D': ['d1', 'd2'], 'E': ['e1', 'e2'], 'F': ['f1', 'f2'], 
        'G': ['g1', 'g2']
    }
    
    stats = {}
    for domain, columns in domains.items():
        domain_scores = []
        for col in columns:
            if col in df.columns:
                domain_scores.extend(df[col].dropna().tolist())
        
        if domain_scores:
            stats[domain] = {
                'mean': sum(domain_scores) / len(domain_scores),
                'count': len(domain_scores),
                'max': max(domain_scores),
                'min': min(domain_scores)
            }
    
    return stats

def calculate_lideranca_stats(df):
    """Calcula estatísticas do questionário de Liderança"""
    if df.empty:
        return {}
    
    stats = {}
    try:
        # Agrupa por questão
        for question in df['question_id'].unique():
            question_data = df[df['question_id'] == question]
            responses = question_data['response'].astype(str).str.upper().tolist()
            
            if responses:
                stats[question] = {
                    'total': len(responses),
                    'distribution': pd.Series(responses).value_counts().to_dict()
                }
    except Exception as e:
        st.error(f"Erro no cálculo de stats de liderança: {e}")
    
    return stats

# ==============================================================================
# 5. INTERFACE DO USUÁRIO - PÁGINAS
# ==============================================================================

def login_page():
    """Página de login"""
    st.title("🔐 Login - Sistema de Inquéritos")
    
    with st.form("login_form"):
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        submit = st.form_submit_button("Entrar")
        
        if submit:
            if not username or not password:
                st.error("Por favor, preencha todos os campos")
                return
                
            user = check_login(username, password)
            if user:
                st.session_state.user = user
                st.session_state.logged_in = True
                st.success(f"Bem-vindo, {user['username']}!")
                st.rerun()
            else:
                st.error("Credenciais inválidas")

def admin_page():
    """Página de administração"""
    st.title("👨‍💼 Administração")
    
    tab1, tab2, tab3, tab4 = st.tabs(["Gestão de Usuários", "Dados HPO", "Dados Liderança", "Backup"])
    
    with tab1:
        st.subheader("Gestão de Usuários")
        
        # Adicionar usuário
        with st.expander("Adicionar Novo Usuário"):
            with st.form("add_user_form"):
                new_username = st.text_input("Nome de usuário")
                new_password = st.text_input("Senha", type="password")
                new_role = st.selectbox("Tipo de usuário", ["gestor", "administrador"])
                add_user_btn = st.form_submit_button("Adicionar Usuário")
                
                if add_user_btn:
                    if add_user(new_username, new_password, new_role):
                        st.success("Usuário adicionado com sucesso!")
                        st.rerun()
                    else:
                        st.error("Erro ao adicionar usuário")
        
        # Listar usuários
        st.subheader("Usuários Existentes")
        users_df = list_users()
        if not users_df.empty:
            for _, user in users_df.iterrows():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
                with col1:
                    st.write(f"**{user['username']}**")
                with col2:
                    st.write(user['role'])
                with col3:
                    st.write(user['created_at'].strftime('%d/%m/%Y %H:%M'))
                with col4:
                    if user['username'] != st.session_state.user['username']:
                        if st.button("🗑️", key=f"del_{user['id']}"):
                            if delete_user(user['id']):
                                st.success("Usuário excluído!")
                                st.rerun()
        else:
            st.info("Nenhum usuário cadastrado")
    
    with tab2:
        st.subheader("Dados HPO")
        hpo_df = load_hpo_responses()
        if not hpo_df.empty:
            st.write(f"Total de respostas: {len(hpo_df)}")
            st.dataframe(hpo_df)
            
            if st.button("🗑️ Apagar Todos os Dados HPO", type="secondary"):
                if st.checkbox("Confirmar exclusão de TODOS os dados HPO"):
                    if delete_all_responses():
                        st.success("Dados apagados com sucesso!")
                        st.rerun()
        else:
            st.info("Nenhum dado HPO coletado")
    
    with tab3:
        st.subheader("Dados de Liderança")
        lideranca_df = load_lideranca_responses()
        if not lideranca_df.empty:
            st.write(f"Total de sessões: {lideranca_df['session_id'].nunique()}")
            st.dataframe(lideranca_df)
        else:
            st.info("Nenhum dado de liderança coletado")
    
    with tab4:
        st.subheader("Backup de Dados")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📥 Exportar Dados HPO"):
                hpo_df = load_hpo_responses()
                if not hpo_df.empty:
                    csv = hpo_df.to_csv(index=False)
                    st.download_button(
                        "⬇️ Baixar CSV",
                        csv,
                        "dados_hpo.csv",
                        "text/csv"
                    )
        
        with col2:
            if st.button("📥 Exportar Dados Liderança"):
                lideranca_df = load_lideranca_responses()
                if not lideranca_df.empty:
                    csv = lideranca_df.to_csv(index=False)
                    st.download_button(
                        "⬇️ Baixar CSV", 
                        csv,
                        "dados_lideranca.csv",
                        "text/csv"
                    )

def survey_hpo_page():
    """Página do questionário HPO"""
    st.title("📊 Questionário HPO")
    
    st.markdown("""
    **Instruções:** Para cada afirmação, avalie de 1 a 5:
    - 1: Discordo totalmente
    - 2: Discordo
    - 3: Neutro
    - 4: Concordo
    - 5: Concordo totalmente
    """)
    
    with st.form("hpo_form"):
        st.subheader("A. Liderança e Gestão")
        a1 = st.slider("A1 - Os líderes comunicam eficazmente a visão da organização", 1, 5, 3)
        a2 = st.slider("A2 - Os gestores apoiam o desenvolvimento da equipa", 1, 5, 3)
        
        st.subheader("B. Processos e Eficiência")
        b1 = st.slider("B1 - Os processos são eficientes e bem definidos", 1, 5, 3)
        b2 = st.slider("B2 - Existe pouca burocracia desnecessária", 1, 5, 3)
        
        st.subheader("C. Inovação e Melhoria")
        c1 = st.slider("C1 - A organização incentiva a inovação", 1, 5, 3)
        c2 = st.slider("C2 - As melhorias são implementadas rapidamente", 1, 5, 3)
        
        st.subheader("D. Pessoas e Competências")
        d1 = st.slider("D1 - As pessoas têm as competências necessárias", 1, 5, 3)
        d2 = st.slider("D2 - Existem oportunidades de desenvolvimento", 1, 5, 3)
        
        st.subheader("E. Clientes e Mercado")
        e1 = st.slider("E1 - Conhecemos bem as necessidades dos clientes", 1, 5, 3)
        e2 = st.slider("E2 - Respondemos rapidamente às mudanças do mercado", 1, 5, 3)
        
        st.subheader("F. Resultados e Performance")
        f1 = st.slider("F1 - Atingimos consistentemente os nossos objetivos", 1, 5, 3)
        f2 = st.slider("F2 - A performance é medida adequadamente", 1, 5, 3)
        
        st.subheader("G. Cultura e Valores")
        g1 = st.slider("G1 - A cultura organizacional é positiva", 1, 5, 3)
        g2 = st.slider("G2 - Os valores são praticados no dia a dia", 1, 5, 3)
        
        comentario = st.text_area("Comentários adicionais (opcional)")
        
        submitted = st.form_submit_button("Submeter Resposta")
        
        if submitted:
            responses = [a1, a2, b1, b2, c1, c2, d1, d2, e1, e2, f1, f2, g1, g2]
            if save_hpo_response(responses, comentario):
                st.success("✅ Resposta submetida com sucesso! Obrigado pela sua participação.")
            else:
                st.error("❌ Erro ao submeter resposta. Tente novamente.")

def survey_lideranca_page():
    """Página do questionário de Liderança"""
    st.title("👑 Questionário de Liderança")
    
    st.markdown("""
    **Instruções:** Responda a cada pergunta com SIM ou NÃO, baseado na sua experiência.
    """)
    
    questions = [
        "O líder comunica claramente as expectativas?",
        "O líder fornece feedback regular e construtivo?",
        "O líder delega responsabilidades adequadamente?",
        "O líder reconhece e valoriza as contribuições?",
        "O líder promove um ambiente de trabalho positivo?",
        "O líder toma decisões de forma consistente?",
        "O líder está disponível para discussões?",
        "O líder inspira confiança e respeito?"
    ]
    
    with st.form("lideranca_form"):
        responses = []
        start_time = time.time()
        
        for i, question in enumerate(questions, 1):
            st.subheader(f"Pergunta {i}")
            st.write(question)
            response = st.radio(
                f"Resposta {i}",
                ["SIM", "NÃO"],
                key=f"q{i}"
            )
            responses.append((f"q{i}", response, time.time() - start_time))
        
        submitted = st.form_submit_button("Submeter Avaliação")
        
        if submitted:
            if save_lideranca_response(responses):
                st.success("✅ Avaliação submetida com sucesso!")
            else:
                st.error("❌ Erro ao submeter avaliação.")

def reports_page():
    """Página de relatórios e análises"""
    st.title("📈 Relatórios e Análises")
    
    tab1, tab2 = st.tabs("Relatório HPO", "Relatório Liderança")
    
    with tab1:
        st.subheader("Análise HPO")
        hpo_df = load_hpo_responses()
        
        if not hpo_df.empty:
            stats = calculate_hpo_stats(hpo_df)
            
            # Métricas gerais
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total de Respostas", len(hpo_df))
            with col2:
                avg_score = sum([s['mean'] for s in stats.values()]) / len(stats) if stats else 0
                st.metric("Pontuação Média", f"{avg_score:.2f}")
            with col3:
                latest = hpo_df['timestamp'].max()
                st.metric("Última Resposta", latest.strftime('%d/%m/%Y'))
            
            # Scores por domínio
            st.subheader("Scores por Domínio")
            for domain, data in stats.items():
                score = data['mean']
                st.write(f"**{domain}**: {score:.2f}/5.0")
                st.progress(score / 5.0)
                
        else:
            st.info("Nenhum dado disponível para análise")
    
    with tab2:
        st.subheader("Análise de Liderança")
        lideranca_df = load_lideranca_responses()
        
        if not lideranca_df.empty:
            stats = calculate_lideranca_stats(lideranca_df)
            
            st.metric("Total de Avaliações", lideranca_df['session_id'].nunique())
            
            for question, data in stats.items():
                st.write(f"**{question}**")
                dist = data['distribution']
                total = data['total']
                
                for response, count in dist.items():
                    percentage = (count / total) * 100
                    st.write(f"- {response}: {count} ({percentage:.1f}%)")
                    st.progress(percentage / 100)
                    
        else:
            st.info("Nenhum dado disponível para análise")

def main_app():
    """Aplicação principal após login"""
    st.sidebar.title("📊 Menu Principal")
    
    # Menu baseado no role
    user_role = st.session_state.user['role']
    
    if user_role == 'administrador':
        menu_options = ["Questionário HPO", "Questionário Liderança", "Relatórios", "Administração"]
    else:
        menu_options = ["Questionário HPO", "Questionário Liderança", "Relatórios"]
    
    choice = st.sidebar.selectbox("Navegação", menu_options)
    
    # Logout button
    if st.sidebar.button("🚪 Sair"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    
    # User info
    st.sidebar.markdown("---")
    st.sidebar.write(f"👤 **{st.session_state.user['username']}**")
    st.sidebar.write(f"🎯 **{st.session_state.user['role']}**")
    
    # Routing
    if choice == "Questionário HPO":
        survey_hpo_page()
    elif choice == "Questionário Liderança":
        survey_lideranca_page()
    elif choice == "Relatórios":
        reports_page()
    elif choice == "Administração":
        admin_page()

def show_deploy_instructions():
    """Mostra instruções de deploy se não houver conexão"""
    st.title("🚀 Configuração do Sistema")
    
    st.error("""
    **Configuração do Banco de Dados Necessária**
    
    Para usar esta aplicação, configure as credenciais do Neon DB:
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🖥️ Desenvolvimento Local")
        st.markdown("""
        1. Crie o arquivo `.streamlit/secrets.toml`
        2. Adicione:
        ```toml
        [postgres]
        host = "ep-seu-host.neon.tech"
        database = "neondb"
        user = "neondb_owner"
        password = "sua-senha"
        port = 5432
        ```
        3. Execute: `streamlit run app.py`
        """)
    
    with col2:
        st.subheader("☁️ Streamlit Cloud")
        st.markdown("""
        1. Acesse [share.streamlit.io](https://share.streamlit.io)
        2. Conecte seu repositório GitHub
        3. Em **Settings → Secrets** adicione:
        ```toml
        [postgres]
        host = "ep-seu-host.neon.tech"
        database = "neondb" 
        user = "neondb_owner"
        password = "sua-senha"
        port = 5432
        ```
        """)
    
    if st.button("🔄 Tentar Reconexão"):
        st.rerun()

# ==============================================================================
# 6. CONFIGURAÇÃO E INICIALIZAÇÃO
# ==============================================================================

# Configuração da página
st.set_page_config(
    page_title="v.Ferreira - Sistema de Inquéritos",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="auto"
)

# CSS personalizado
st.markdown("""
    <style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    @media (max-width: 768px) {
        .main .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }
        h1 { font-size: 1.8rem !important; }
        h2 { font-size: 1.5rem !important; }
        h3 { font-size: 1.3rem !important; }
        .stButton > button { width: 100%; margin-bottom: 0.5rem; }
    }
    .stSlider > div > div > div > div {
        background-color: #1E90FF !important;
    }
    .good-performance { color: #27ae60; font-weight: bold; }
    .poor-performance { color: #e74c3c; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 7. EXECUÇÃO PRINCIPAL
# ==============================================================================

# Inicializa conexão
conn = init_connection()

# Se não há conexão, mostra instruções
if conn is None:
    show_deploy_instructions()
    st.stop()

# Inicializa banco de dados
init_db()

# Verifica autenticação
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

# Routing principal
if not st.session_state.logged_in:
    login_page()
else:
    main_app()