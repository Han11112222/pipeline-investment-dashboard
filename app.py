import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --------------------------------------------------------------------------
# [설정] 페이지 기본
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

DEFAULT_FILE_NAME = "리스트_20260129.xlsx"

# --------------------------------------------------------------------------
# [함수] 데이터 전처리 & 파싱
# --------------------------------------------------------------------------
def clean_column_names(df):
    """컬럼명 정규화 (공백/줄바꿈 제거)"""
    df.columns = [str(c).replace("\n", "").replace(" ", "").replace("\t", "").strip() for c in df.columns]
    return df

def find_col(df, keywords):
    """키워드로 컬럼 찾기"""
    for col in df.columns:
        for kw in keywords:
            if kw in col:
                return col
    return None

def parse_value(value):
    """숫자만 추출 (에러 방지)"""
    try:
        if pd.isna(value) or value == '':
            return 0.0
        clean_str = str(value).replace(',', '')
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", clean_str)
        if numbers:
            return float(numbers[0])
        return 0.0
    except:
        return 0.0

# --------------------------------------------------------------------------
# [함수] 판관비 & 메인 역산 로직
# --------------------------------------------------------------------------
def calculate_all_rows(df, target_irr, tax_rate, period, cost_maint_m, cost_admin_hh, cost_admin_m):
    # PVIFA (연금현가계수)
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    
    # 엑셀 컬럼 매칭
    col_invest = find_col(df, ["배관투자", "투자금액"])
    col_contrib = find_col(df, ["시설분담금", "분담금"])
    col_vol = find_col(df, ["연간판매량", "판매량계"])
    col_profit = find_col(df, ["연간판매수익", "판매수익"])
    col_len = find_col(df, ["길이", "연장"])
    col_hh = find_col(df, ["계획전수", "전수", "세대수"])
    col_usage = find_col(df, ["용도", "구분"])

    if not col_invest or not col_vol or not col_profit:
        return df, "❌ 엑셀 파일에서 핵심 컬럼(투자비, 판매량, 수익 등)을 찾을 수 없습니다."

    for index, row in df.iterrows():
        try:
            # 데이터 파싱
            investment = parse_value(row.get(col_invest))
            contribution = parse_value(row.get(col_contrib))
            current_vol = parse_value(row.get(col_vol))
            current_profit = parse_value(row.get(col_profit))
            length = parse_value(row.get(col_len))
            households = parse_value(row.get(col_hh))
            usage_str = row.get(col_usage, "")

            if current_vol <= 0 or investment <= 0:
                results.append(0)
                continue

            # --- 역산 시작 ---
            net_investment = investment - contribution
            
            # 1. 자본회수 필요액 (Required OCF)
            if net_investment <= 0:
                required_capital_recovery = 0
            else:
                required_capital_recovery = net_investment / pvifa

            # 2. 판관비 (용도별 자동 적용)
            maint_cost = length * cost_maint_m
            usage = str(usage_str).strip()
            if any(k in usage for k in ['공동', '단독', '주택', '아파트', '주거']):
                admin_cost = households * cost_admin_hh
            else:
                admin_cost = length * cost_admin_m
            total_sga = maint_cost + admin_cost
            
            # 3. 감가상각비 & 세전이익 & 필요마진
            depreciation = investment / period
            required_ebit = (required_capital_recovery - depreciation) / (1 - tax_rate)
            required_gross_margin = required_ebit + total_sga + depreciation
            
            # 4. 목표 판매량
            unit_margin = current_profit / current_vol
            if unit_margin <= 0:
                results.append(0)
                continue

            required_volume = required_gross_margin / unit_margin
            results.append(max(0, required_volume)) # 소수점은 나중에 포맷팅

        except:
            results.append(0)
    
    # 결과 컬럼 생성
    df['최소경제성만족판매량'] = results
    
    # 달성률 계산: (현재 / 목표) * 100
    # 목표가 0이면(이미 회수됨), 달성률은 100% 이상으로 간주 (여기선 편의상 100 표시 혹은 999)
    df['달성률'] = df.apply(lambda x: (x[col_vol] / x['최소경제성만족판매량'] * 100) if x['최소경제성만족판매량'] > 0 else 0, axis=1)
    
    # 목표가 0인 경우(투자비 회수완료)의 처리: 달성률 100%로 표기하거나 별도 처리 가능.
    # 여기서는 계산된 값이 0이면 -> "달성완료" 의미로 로직상 0이 나오지만, 
    # 투자비 회수가 끝난 건은 보통 달성률을 논하기보다 "확보 완료"로 봅니다.
    # 표에서는 0%로 나오지 않게, 목표가 0인데 현재판매량이 있으면 999% 등으로 처리하는게 식별에 좋습니다.
    # 코드 수정: 목표가 0이고 현재판매량이 있으면 999.9% (달성완료)
    df['달성률'] = df.apply(
        lambda x: (x[col_vol] / x['최소경제성만족판매량'] * 100) if x['최소경제성만족판매량'] > 1 else (999.9 if x[col_vol] > 0 else 0), 
        axis=1
    )

    return df, None

# --------------------------------------------------------------------------
# [UI 구성] 사이드바 (입력 제어)
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 파일 및 설정")
    data_source = st.radio("소스 선택", ("GitHub 파일", "엑셀 업로드"))
    if data_source == "엑셀 업로드":
        uploaded_file = st.file_uploader("파일 업로드", type=['xlsx'])
    
    st.divider()
    
    st.subheader("⚙️ 분석 기준 (수정 가능)")
    target_irr_percent = st.number_input("목표 IRR (%)", value=6.15, format="%.2f", step=0.01)
    tax_rate_percent = st.number_input("세율 (법인세+주민세 %)", value=20.9, format="%.1f", step=0.1)
    period_input = st.number_input("감가상각 기간 (년)", value=30, step=1)
    
    st.subheader("💰 비용 단가")
    cost_maint_m_input = st.number_input("배관유지비 (원/m)", value=8222)
    cost_admin_hh_input = st.number_input("일반관리비 (원/전, 주택)", value=6209)
    cost_admin_m_input = st.number_input("일반관리비 (원/m, 기타)", value=13605)

    # 변수 변환
    target_irr = target_irr_percent / 100
    tax_rate = tax_rate_percent / 100

# --------------------------------------------------------------------------
# [UI 구성] 메인 화면
# --------------------------------------------------------------------------
st.title("💰 도시가스 배관투자 경제성 분석기")

# 상단 요약 배너
c1, c2, c3, c4 = st.columns(4)
c1.metric("목표 IRR", f"{target_irr_percent}%")
c2.metric("적용 세율", f"{tax_rate_percent}%")
c3.metric("유지비/m", f"{cost_maint_m_input:,}원")
c4.metric("관리비/전", f"{cost_admin_hh_input:,}원")

# 데이터 로드
df = None
if data_source == "GitHub 파일":
    if os.path.exists(DEFAULT_FILE_NAME):
        df = pd.read_excel(DEFAULT_FILE_NAME, engine='openpyxl')
    else:
        st.warning(f"⚠️ {DEFAULT_FILE_NAME} 파일 없음")
elif data_source == "엑셀 업로드" and uploaded_file:
    df = pd.read_excel(uploaded_file, engine='openpyxl')

# 결과 출력
if df is not None:
    df = clean_column_names(df)
    
    # 계산 실행
    result_df, msg = calculate_all_rows(
        df, target_irr, tax_rate, period_input, 
        cost_maint_m_input, cost_admin_hh_input, cost_admin_m_input
    )
    
    if msg:
        st.error(msg)
    else:
        st.divider()
        st.subheader("📊 분석 결과 요약")
        
        # 1. 뷰 데이터프레임 구성 (보여줄 컬럼만 쏙 뽑기)
        # 매핑: {표시할이름 : 실제컬럼키워드}
        view_cols_map = {
            "공사관리번호": ["공사관리번호", "관리번호"],
            "투자분석명": ["투자분석명", "공사명"],
            "용도": ["용도"],
            "현재판매량(MJ)": ["연간판매량", "판매량계"],
            "최소경제성만족판매량(MJ)": ["최소경제성만족판매량"],  # 요청하신 컬럼
            "달성률": ["달성률"]
        }
        
        final_df = pd.DataFrame()
        for label, keywords in view_cols_map.items():
            found = find_col(result_df, keywords)
            if found:
                final_df[label] = result_df[found]
        
        # 2. 표 출력 (여기가 중요: 천단위 콤마 & 소수점 포맷)
        st.dataframe(
            final_df,
            column_config={
                "공사관리번호": st.column_config.TextColumn("공사관리번호"),
                "투자분석명": st.column_config.TextColumn("투자분석명"),
                "용도": st.column_config.TextColumn("용도"),
                
                # [핵심] 천단위 콤마 (format="%,d" 또는 "%,.0f")
                "현재판매량(MJ)": st.column_config.NumberColumn(
                    "현재판매량(MJ)", format="%,.0f"
                ),
                # [핵심] 천단위 콤마 + 강조
                "최소경제성만족판매량(MJ)": st.column_config.NumberColumn(
                    "최소경제성만족판매량(MJ)", format="%,.0f"
                ),
                # [핵심] 소수점 1자리 + %
                "달성률": st.column_config.NumberColumn(
                    "달성률(%)", format="%.1f%%" 
                ),
            },
            use_container_width=True,
            hide_index=True
        )

        # 엑셀 다운로드
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False)
            writer.sheets['Sheet1'].set_column('A:Z', 18)
        st.download_button("📥 전체 결과 엑셀 다운로드", output.getvalue(), "분석결과.xlsx", "primary")

        # ------------------------------------------------------------------
        # 상세 산출 근거 (하단 설명)
        # ------------------------------------------------------------------
        st.divider()
        st.subheader("🧮 산출 근거 상세 (Step-by-Step Breakdown)")
        
        name_col = find_col(result_df, ["투자분석명", "공사명"])
        if name_col:
            project_list = result_df[name_col].unique()
            selected_project = st.selectbox("프로젝트 선택 (상세 계산 과정 보기):", project_list)
            
            row = result_df[result_df[name_col] == selected_project].iloc[0]
            
            # 변수 추출 및 재계산 (화면 표시용)
            # (계산 로직은 위와 동일하게 적용하여 보여줌)
            col_inv = find_col(result_df, ["배관투자"])
            col_cont = find_col(result_df, ["분담금"])
            col_vol = find_col(result_df, ["판매량계", "연간판매량"])
            col_prof = find_col(result_df, ["판매수익"])
            col_len = find_col(result_df, ["길이"])
            col_hh = find_col(result_df, ["계획전수"])
            col_use = find_col(result_df, ["용도"])

            inv = parse_value(row.get(col_inv))
            cont = parse_value(row.get(col_cont))
            vol = parse_value(row.get(col_vol))
            profit = parse_value(row.get(col_prof))
            length = parse_value(row.get(col_len))
            hh = parse_value(row.get(col_hh))
            usage = str(row.get(col_use, ""))

            pvifa = (1 - (1 + target_irr) ** (-period_input)) / target_irr
            net_inv = inv - cont
            req_capital = max(0, net_inv / pvifa)
            
            maint_c = length * cost_maint_m_input
            if any(k in usage for k in ['공동', '단독', '주택', '아파트']):
                admin_c = hh * cost_admin_hh_input
                type_txt = "주택용"
            else:
                admin_c = length * cost_admin_m_input
                type_txt = "비주택"
            total_sga = maint_c + admin_c
            
            dep = inv / period_input
            req_ebit = (req_capital - dep) / (1 - tax_rate)
            req_gross = req_ebit + total_sga + dep
            unit_margin = profit / vol if vol > 0 else 0
            final_vol = req_gross / unit_margin if unit_margin > 0 else 0

            # 2단 레이아웃 표시
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**1. 투자 정보**")
                st.write(f"- 순투자액: **{net_inv:,.0f}** 원")
                st.write(f"- 시설: {length}m / {hh}세대 / {type_txt}")
            with c2:
                st.markdown("**2. 수익 구조**")
                st.write(f"- 현재 판매량: **{vol:,.0f}** MJ")
                st.write(f"- 단위 마진: **{unit_margin:.2f}** 원/MJ")

            st.info(f"""
            **[최종 계산]**
            1. 필요 자본회수액(OCF) = {req_capital:,.0f} 원
            2. 연간 운영비(판관비) = {total_sga:,.0f} 원
            3. 필요 마진총액 = {req_gross:,.0f} 원
            
            👉 **최소경제성만족판매량** = {req_gross:,.0f} ÷ {unit_margin:.2f} = **{max(0, final_vol):,.0f} MJ**
            """)
