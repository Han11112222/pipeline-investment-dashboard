import pandas as pd
import numpy as np
import re
import os

def clean_column_names(df):
    """컬럼명 앞뒤 공백 제거 및 특수문자 정리"""
    df.columns = [c.strip() for c in df.columns]
    return df

def parse_cost_string(value):
    """'8,222원/(m,연)' 같은 문자열에서 숫자만 추출"""
    if pd.isna(value) or value == '':
        return 0.0
    # 정규표현식: 숫자와 소수점(.)만 남김
    numbers = re.findall(r"[\d\.]+", str(value).replace(',', ''))
    if numbers:
        return float(numbers[0])
    return 0.0

def calculate_irr_target_volume(input_file, output_file):
    print(f"📂 파일 로딩 중: {input_file}...")
    
    # 엑셀 또는 CSV 읽기
    if input_file.endswith('.csv'):
        df = pd.read_csv(input_file)
    else:
        df = pd.read_excel(input_file)

    # 컬럼명 공백 제거 (에러 방지)
    df = clean_column_names(df)

    # --- 상수 설정 (정책에 따라 변경 가능) ---
    TARGET_IRR = 0.0615  # 목표 IRR 6.15%
    TAX_RATE = 0.209     # 법인세+주민세 (20.9%)
    PERIOD = 30          # 감가상각 기간 30년

    # PVIFA (연금현가계수) 계산: 매년 동일 금액 회수 시 필요 계수
    pvifa = (1 - (1 + TARGET_IRR) ** (-PERIOD)) / TARGET_IRR

    results = []
    
    print("🚀 경제성 분석 역산(Goal Seek) 진행 중...")

    for index, row in df.iterrows():
        try:
            # 1. 기초 데이터 추출 (컬럼명 매칭 주의)
            # 엑셀 파일의 실제 컬럼명을 기준으로 매핑
            investment = float(row.get('배관투자금액  (원)', 0) or row.get('배관투자금액', 0))
            contribution = float(row.get('총시설분담금', 0))
            current_sales_volume = float(row.get('연간판매량계(MJ)', 0))
            current_sales_profit = float(row.get('연간판매수익', 0)) # 마진 총액
            
            length = float(row.get('길이  (m)', 0) or row.get('길이 (m)', 0))
            households = float(row.get('계획전수', 0))

            # 2. 판관비 파싱 (문자열 -> 숫자 변환)
            maint_cost_per_m = parse_cost_string(row.get('연간 배관유지비(m)', 0))
            admin_cost_per_hh = parse_cost_string(row.get('연간 일반관리비(전)', 0))
            
            # --- 예외 처리 ---
            if current_sales_volume <= 0 or investment <= 0:
                results.append(0)
                continue

            # --- 핵심 로직 시작 ---

            # A. 순투자액 (Net Investment)
            net_investment = investment - contribution
            
            # 시설분담금이 더 많으면 즉시 회수이므로 0 처리
            if net_investment <= 0:
                results.append(0) 
                continue

            # B. 연간 총 판관비(SG&A) 계산
            # 배관유지비(길이 비례) + 일반관리비(세대수 비례)
            annual_sga = (length * maint_cost_per_m) + (households * admin_cost_per_hh)

            # C. 단위당 마진 (MJ당 공헌이익)
            unit_margin = current_sales_profit / current_sales_volume
            if unit_margin <= 0:
                results.append(0)
                continue

            # D. 감가상각비 (정액법)
            depreciation = investment / PERIOD

            # E. 목표 IRR 달성을 위한 '세후 영업현금흐름(OCF)' 역산
            # Net Investment = OCF * PVIFA
            required_ocf = net_investment / pvifa

            # F. 세금 효과를 고려한 '필요 총이익(Gross Margin)' 도출
            # 공식: Required_Margin = [ (OCF - Dep) / (1-Tax) ] + Dep + SG&A
            
            # (1) 세후이익 -> 세전이익 환산
            required_pretax_profit = (required_ocf - depreciation) / (1 - TAX_RATE)
            
            # (2) 판관비와 감가상각비를 더해 '필요 마진총액' 계산
            required_gross_margin = required_pretax_profit + annual_sga + depreciation

            # G. 최종 목표 판매량(Q) 계산
            required_volume = required_gross_margin / unit_margin
            
            results.append(round(required_volume, 2))

        except Exception as e:
            # 데이터 포맷 에러 시 0 처리 (로그 출력 가능)
            results.append(0)

    # 결과 컬럼 추가
    df['최소경제성만족판매량'] = results
    
    # 엑셀로 저장
    df.to_excel(output_file, index=False)
    print(f"✅ 분석 완료! 결과가 저장되었습니다: {output_file}")
    
    # 간단한 리포트 출력
    print("\n[분석 결과 미리보기]")
    print(df[['투자분석명', '연간판매량계(MJ)', '최소경제성만족판매량']].head())

if __name__ == "__main__":
    # 파일명은 실제 깃허브에 올릴 파일명으로 수정하세요
    input_filename = '리스트_20260128.xlsx' 
    output_filename = '결과_분석완료.xlsx'
    
    if os.path.exists(input_filename) or os.path.exists(input_filename + ' - 리스트.csv'):
        # CSV 파일인 경우 대응 (업로드하신 파일명 기준)
        if not os.path.exists(input_filename):
            input_filename = '리스트_20260128.xlsx - 리스트.csv'
            
        calculate_irr_target_volume(input_filename, output_filename)
    else:
        print(f"❌ '{input_filename}' 파일이 없습니다. 같은 폴더에 파일을 넣어주세요.")
