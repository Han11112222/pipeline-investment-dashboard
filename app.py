import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --- 페이지 설정 ---
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# [설정] 깃허브에 저장된 기본 파일명
DEFAULT_FILE_NAME = "리스트_20260128.xlsx"

# --- [함수] 데이터 전처리 ---
def clean_column_names(df):
    df.columns = [c.strip() for c in df.columns]
    return df

def parse_cost_string(value):
    """'8,222원/(m,연)' 같은 텍스트에서 숫자만 추출"""
    if pd.isna(value) or value == '':
        return 0.0
    clean_str = str(value).replace(',', '')
    numbers = re.findall(r"[\d\.]+", clean_str)
    if numbers:
        return float(numbers[0])
    return 0.0

# --- [함수] 핵심 역산 로직 (모든 인자 활용) ---
def calculate_target_volume(df, target_irr, tax_rate, period):
    
    # 연금현가계수(PVIFA) 계산
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    
    # 진행률바
    progress_text = "전체 인자(투자비, 판관비, 감가상각, 세금 등)를 반영하여 역산 중..."
    progress_bar = st.progress(0, text=progress_text)
    total_rows = len(df)

    for index, row in df.iterrows():
        try:
            # 1. [투자비 관련] 순투자액 계산
            investment = float(row.get('배관투자금액  (원) ', 0) or row.get('배관투자금액', 0))
            contribution = float(row.get('총시설분담금', 0))
            net_investment = investment - contribution

            # 2. [기존 실적] 현재 판매량 및 수익 구조 파악
            current_sales_volume = float(row.get('연간판매량계(MJ)', 0))
            current_sales_profit = float(row.get('연간판매수익', 0)) 
            
            # 3. [비용 인자] 판관비 계산을 위한 기초 데이터
            length = float(row.get('길이  (m) ', 0) or row.get('길이 (m)', 0) or row.get('길이', 0))
            households = float(row.get('계획전수', 0))

            # 4. [비용 파싱] 텍스트에서 단가 추출
            maint_cost_per_m = parse_cost_string(row.get('연간 배관유지비(m)', 0))
            admin_cost_per_hh = parse_cost_string(row.get('연간 일반관리비(전)', 0))
            admin_cost_per_m = parse_cost_string(row.get('연간 일반관리비(m)', 0))

            # --- 예외 처리 ---
            if current_sales_volume <= 0 or investment <= 0 or net_investment <= 0:
                results.append(0) # 이미 투자 회수되었거나 데이터 없음
                continue

            # --- [핵심] IRR 6.15% 역산 시뮬레이션 ---
            
            # Step A. 목표 달성을 위해 필요한 현금흐름(OCF) 산출
            # (순투자액을 30년 동안 IRR 6.15%로 회수하기 위한 연간 현금)
            required_ocf = net_investment / pvifa

            # Step B. 운영비용(판관비) 총액 계산
            # (배관길이 x 유지비) + (세대수 x 일반관리비)
            total_sga = (length * maint_cost_per_m) + (households * admin_cost_per_hh) + (length * admin_cost_per_m)
            
            # Step C. 감가상각비 (세금 절감 효과 반영용)
            depreciation = investment / period

            # Step D. 필요 세전이익(EBIT) 역산 (법인세+주민세 효과 고려)
            # OCF = (EBIT * (1-Tax)) + Dep  --->  EBIT = (OCF - Dep) / (1-Tax)
            required_pretax_profit = (required_ocf - depreciation) / (1 - tax_rate)

            # Step E. 필요 공헌이익(Gross Margin) 도출
            # 세전이익을 남기기 위해 판관비와 감가상각비를 커버해야 함
            required_gross_margin = required_pretax_profit + total_sga + depreciation

            # Step F. 단위당 마진(Unit Margin) 계산
            unit_margin = current_sales_profit / current_sales_volume
            
            if unit_margin <= 0:
                results.append(0)
                continue

            # Step G. 최종 목표 판매량(Q) 도출
            required_volume = required_gross_margin / unit_margin
            
            results.append(round(required_volume, 2))

        except Exception:
            results.append(0)
        
        if index % 10 == 0:
            progress_bar.progress(min((index + 1) / total_rows, 1.0))

    progress_bar.progress(1.0)
    df['최소경제성만족판매량'] = results
    return df

# =========================================================
# [UI 구성] 사이드바 (설정 및 파일)
# =========================================================
with st.sidebar:
    st.header("📂 데이터 및 기준 설정")
    
    # 1. 파일 선택 (탭 기능 대체)
    data_source = st.radio(
        "분석할 데이터 선택",
        ("GitHub 기본 파일", "엑셀 직접 업로드"),
        index=0 # 기본값: GitHub
    )
    
    uploaded_file = None
    if data_source == "엑셀 직접 업로드":
        uploaded_file = st.file_uploader("엑셀 파일 선택 (.xlsx)", type=['xlsx'])
    
    st.divider()
    
    # 2. 분석 파라미터
    st.subheader("⚙️ 분석 기준 (IRR Target)")
    target_irr = st.number_input("목표 IRR (%)", value=6.15, format="%.2f") / 100
    tax_rate = st.number_input("세율 (법인세+주민세, %)", value=20.9, format="%.1f") / 100
    period = st.number_input("상각 기간 (년)", value=30)
    
    st.info(f"현재 기준: IRR {target_irr*100}% / 30년 상각")

# =========================================================
# [UI 구성] 메인 화면
# =========================================================
st.title("💰 도시가스 배관투자 경제성 역산 분석기")

# [분석 개요] 업데이트
st.markdown("""
### 📝 분석 개요 및 목적
이 도구는 **2020~2024년 기 투자된 구간**의 효율성을 검증하기 위해, **목표 IRR(6.15%)을 달성하기 위한 최소 판매량(BEP)**을 역산합니다.
* **계산 원리 (Goal Seek):** 단순 마진뿐만 아니라 **순투자액, 감가상각비, 법인세 효과(Tax Shield), 판관비(유지비+일반관리비)** 등 모든 비용 인자를 고려하여 정밀하게 역산합니다.
* **최종 목적:** 현재 판매량과 비교하여 경제성을 만족하는지 판단하는 지표인 **'최소경제성만족판매량'**을 산출합니다.
""")
st.divider()

# --- 데이터 로딩 로직 ---
df = None

if data_source == "GitHub 기본 파일":
    if os.path.exists(DEFAULT_FILE_NAME):
        try:
            df = pd.read_excel(DEFAULT_FILE_NAME)
            st.success(f"✅ 깃허브에 있는 '{DEFAULT_FILE_NAME}' 파일을 성공적으로 불러왔습니다.")
        except Exception as e:
            st.error(f"❌ 파일 읽기 실패: {e}")
    else:
        st.warning(f"⚠️ 깃허브 저장소에 '{DEFAULT_FILE_NAME}' 파일이 없습니다.")
        
elif data_source == "엑셀 직접 업로드":
    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            st.success("✅ 업로드한 파일을 성공적으로 불러왔습니다.")
        except Exception as e:
            st.error(f"❌ 파일 읽기 실패: {e}")
    else:
        st.info("👈 좌측 사이드바에서 파일을 업로드해주세요.")

# --- 분석 실행 및 결과 표시 ---
if df is not None:
    # 컬럼 정리
    df = clean_column_names(df)
    
    # 계산 실행
    result_df = calculate_target_volume(df, target_irr, tax_rate, period)
    
    st.subheader("📊 분석 결과: 최소경제성만족판매량 산출")
    
    # 결과 데이터프레임 스타일링
    # 사용자가 가장 보고 싶어하는 '최소경제성만족판매량'을 강조
    display_cols = ['공사관리번호', '투자분석명', '용도', '연간판매량계(MJ)', '최소경제성만족판매량']
    # 실제 존재하는 컬럼만 선택
    valid_cols = [c for c in display_cols if c in result_df.columns]
    
    st.dataframe(
        result_df[valid_cols].style.background_gradient(subset=['최소경제성만족판매량'], cmap="Oranges"),
        use_container_width=True,
        height=500
    )

    # 다운로드 버튼
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
        worksheet = writer.sheets['Sheet1']
        worksheet.set_column('A:Z', 15)
        
    st.download_button(
        label="📥 결과 엑셀 다운로드 (전체 데이터 포함)",
        data=output.getvalue(),
        file_name="최소경제성만족판매량_분석결과.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
