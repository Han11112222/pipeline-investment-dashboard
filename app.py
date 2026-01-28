import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --------------------------------------------------------------------------
# [기본 설정]
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")
st.title("💰 도시가스 배관투자 경제성 역산 분석기")

# 깃허브에 있는 파일명 (정확해야 함)
DEFAULT_FILE_NAME = "리스트_20260128.xlsx"

# --------------------------------------------------------------------------
# [함수 1] 스마트 데이터 전처리 (에러 방지)
# --------------------------------------------------------------------------
def find_col(df, keyword):
    """
    엑셀 컬럼명에 공백이나 오타가 있어도 키워드로 찾아내는 함수
    예: '투자금액'만 입력해도 '배관투자금액  (원) '을 찾아냄
    """
    for col in df.columns:
        if keyword in str(col).replace(" ", ""): # 공백 제거 후 비교
            return col
    return None

def parse_value(value):
    """
    '8,222원/(m,연)' 같은 텍스트에서 숫자(8222.0)만 쏙 뽑아내는 함수
    """
    if pd.isna(value) or value == '':
        return 0.0
    # 쉼표 제거
    clean_str = str(value).replace(',', '')
    # 숫자와 소수점만 남기기
    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", clean_str)
    if numbers:
        return float(numbers[0])
    return 0.0

# --------------------------------------------------------------------------
# [함수 2] 핵심 역산 로직 (Reverse Engineering)
# --------------------------------------------------------------------------
def calculate_min_volume(df, target_irr, tax_rate, period):
    
    # 1. 연금현가계수 (PVIFA) 계산
    # IRR 6.15%를 달성하기 위해 매년 회수해야 하는 비율 역산
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    
    # 컬럼 자동 매칭 (스마트 검색)
    col_invest = find_col(df, "투자금액")
    col_contrib = find_col(df, "시설분담금")
    col_vol = find_col(df, "연간판매량")
    col_profit = find_col(df, "연간판매수익") # 이것이 핵심! (마진 총액)
    col_len = find_col(df, "길이")
    col_hh = find_col(df, "계획전수")
    
    # 판관비 컬럼
    col_maint = find_col(df, "배관유지비")
    col_admin_hh = find_col(df, "일반관리비(전)")
    col_admin_m = find_col(df, "일반관리비(m)")

    # 진행바
    progress_bar = st.progress(0, text="회사 내부 로직(세후 OCF)으로 역산 중...")
    total_rows = len(df)

    for index, row in df.iterrows():
        try:
            # --- A. 기초 데이터 추출 (숫자만 파싱) ---
            investment = parse_value(row.get(col_invest, 0))
            contribution = parse_value(row.get(col_contrib, 0))
            
            # 현재 실적
            current_sales_volume = parse_value(row.get(col_vol, 0))
            current_sales_profit = parse_value(row.get(col_profit, 0))
            
            # 시설 정보
            length = parse_value(row.get(col_len, 0))
            households = parse_value(row.get(col_hh, 0))

            # 판관비 단가
            maint_cost_per_m = parse_value(row.get(col_maint, 0))
            admin_cost_per_hh = parse_value(row.get(col_admin_hh, 0))
            admin_cost_per_m = parse_value(row.get(col_admin_m, 0))

            # 예외처리: 데이터 부족 시 패스
            if current_sales_volume <= 0 or investment <= 0:
                results.append(0)
                continue

            # --- B. 역산 로직 (Goal Seek) ---
            
            # 1. 순투자액 (Net Investment)
            net_investment = investment - contribution
            
            # 2. 목표 현금흐름 (Required OCF)
            # 순투자액을 30년간 6.15%로 회수하려면 매년 얼마의 현금이 들어와야 하는가?
            if net_investment <= 0:
                # 분담금으로 투자비 전액 회수 시, 자본회수 부담 없음 (0원)
                # 단, 운영비(판관비)는 커버해야 하므로 로직 계속 진행
                required_capital_recovery = 0 
            else:
                required_capital_recovery = net_investment / pvifa

            # 3. 연간 총 판관비 (SG&A)
            total_sga = (length * maint_cost_per_m) + (households * admin_cost_per_hh) + (length * admin_cost_per_m)
            
            # 4. 연간 감가상각비 (Depreciation)
            depreciation = investment / period

            # 5. [핵심] 필요 세전 영업이익 (Required EBIT)
            # 공식: OCF = (EBIT * (1-Tax)) + Dep
            # 변형: EBIT = (OCF - Dep) / (1-Tax)
            # 여기서 OCF는 '자본회수필요액(required_capital_recovery)'을 의미
            
            required_ebit = (required_capital_recovery - depreciation) / (1 - tax_rate)

            # 6. 필요 마진총액 (Required Gross Margin)
            # EBIT = 마진총액 - 판관비 - 감가상각비
            # 마진총액 = EBIT + 판관비 + 감가상각비
            required_gross_margin = required_ebit + total_sga + depreciation

            # 7. 단위당 마진 (Unit Margin, 원/MJ)
            # 현재 엑셀의 '연간판매수익(총액) / 연간판매량'
            unit_margin = current_sales_profit / current_sales_volume
            
            if unit_margin <= 0:
                results.append(0)
                continue

            # 8. 최종 목표 판매량 (Target Volume)
            required_volume = required_gross_margin / unit_margin
            
            # 결과가 음수면 0 (이미 초과수익 상태)
            results.append(max(0, round(required_volume, 2)))

        except Exception:
            results.append(0)
        
        if index % 10 == 0:
            progress_bar.progress(min((index + 1) / total_rows, 1.0))

    progress_bar.progress(1.0)
    df['최소경제성만족판매량'] = results
    
    # 달성률 계산 (현재판매량 / 최소판매량)
    # 최소판매량이 0이면 이미 달성(999%)으로 표기
    df['달성률(%)'] = df.apply(lambda x: round((x[col_vol] / x['최소경제성만족판매량'] * 100), 1) if x['최소경제성만족판매량'] > 0 and col_vol else 999.9, axis=1)

    return df

# --------------------------------------------------------------------------
# [UI 구성] 사이드바 (설정)
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 데이터 파일 선택")
    data_source = st.radio(
        "사용할 파일",
        ("GitHub 기본 파일", "엑셀 직접 업로드"),
        index=0
    )
    
    uploaded_file = None
    if data_source == "엑셀 직접 업로드":
        uploaded_file = st.file_uploader("엑셀 파일 선택", type=['xlsx'])
    
    st.divider()
    
    st.subheader("⚙️ 분석 기준 (IRR 6.15%)")
    target_irr = st.number_input("목표 IRR (%)", value=6.15, format="%.2f") / 100
    tax_rate = st.number_input("세율 (법인세+주민세, %)", value=20.9, format="%.1f") / 100
    period = st.number_input("상각 기간 (년)", value=30)
    
    st.info("""
    **[계산 공식 참고]**
    세후 OCF = 세후순이익 + 감가상각비
    세후순이익 = 세전이익 * (1-세율)
    """)

# --------------------------------------------------------------------------
# [UI 구성] 메인 화면
# --------------------------------------------------------------------------
st.markdown("""
### 💰 도시가스 배관투자 경제성 분석기
**[목적]** 2020~2024년 기 투자구간에 대해 **IRR 6.15%를 달성하기 위한 최소 판매량**을 검증합니다.  
**[분석방법]** 회사 내부 양식(투자.csv)의 **'세후 영업현금흐름(OCF)'** 산출 로직을 역산하여, 투자비 회수와 운영비(판관비)를 모두 커버하는 판매량을 산출합니다.
""")
st.divider()

# 데이터 로딩
df = None

if data_source == "GitHub 기본 파일":
    if os.path.exists(DEFAULT_FILE_NAME):
        try:
            # openpyxl 엔진 명시
            df = pd.read_excel(DEFAULT_FILE_NAME, engine='openpyxl')
            st.success(f"✅ 깃허브 파일 '{DEFAULT_FILE_NAME}' 로드 성공!")
        except Exception as e:
            st.error(f"❌ 파일 읽기 실패: {e}")
    else:
        st.warning(f"⚠️ '{DEFAULT_FILE_NAME}' 파일이 없습니다.")
        
elif data_source == "엑셀 직접 업로드" and uploaded_file:
    df = pd.read_excel(uploaded_file, engine='openpyxl')
    st.success("✅ 파일 업로드 성공!")

# 결과 출력
if df is not None:
    # 계산 실행
    result_df = calculate_min_volume(df, target_irr, tax_rate, period)
    
    st.subheader("📊 분석 결과: 최소경제성만족판매량")
    
    # 보여줄 컬럼 찾기 (스마트 매칭)
    display_cols = []
    target_keywords = ["공사관리번호", "투자분석명", "용도", "연간판매량", "최소경제성만족판매량", "달성률"]
    
    for kw in target_keywords:
        found = find_col(result_df, kw)
        if found:
            display_cols.append(found)
            
    # 데이터프레임 표시 (최소판매량 강조)
    target_col = find_col(result_df, "최소경제성만족판매량")
    if target_col:
        st.dataframe(
            result_df[display_cols].style.background_gradient(subset=[target_col], cmap="Oranges"),
            use_container_width=True
        )
    else:
        st.dataframe(result_df[display_cols], use_container_width=True)

    # 다운로드 버튼
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
        worksheet = writer.sheets['Sheet1']
        worksheet.set_column('A:Z', 18)
        
    st.download_button(
        label="📥 결과 엑셀 다운로드 (Click)",
        data=output.getvalue(),
        file_name="경제성분석_최소판매량_결과.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
