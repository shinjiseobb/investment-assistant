document.addEventListener("DOMContentLoaded", () => {
  console.log("[PAGE] 페이지 로드 완료");

  const searchForm = document.getElementById("search-form");
  const stockCodeInput = document.getElementById("stock-code");
  const fetchBtn = document.getElementById("fetch-btn");
  const loadingBox = document.getElementById("loading-box");
  const errorBox = document.getElementById("error-box");
  const resultContainer = document.getElementById("result-container");

  // 빠른 입력 예시 버튼 연결
  document.querySelectorAll(".example-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const code = btn.getAttribute("data-code");
      stockCodeInput.value = code;
      fetchStockData(code);
    });
  });

  // 검색 폼 제출 이벤트
  searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const code = stockCodeInput.value.trim();
    fetchStockData(code);
  });

  async function fetchStockData(code) {
    console.log(`[SEARCH] 종목 수집 요청 시작 (종목코드: ${code})`);

    // UI 초기화
    loadingBox.classList.remove("hidden");
    errorBox.classList.add("hidden");
    errorBox.innerHTML = "";
    fetchBtn.disabled = true;

    try {
      const response = await fetch("/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });

      const data = await response.json();

      // 부분/전체 에러 표시
      if (data.errors && data.errors.length > 0) {
        console.error("[ERROR] 수집 중 오류 발생:", data.errors);
        renderErrors(data.errors);
      }

      // 종목명을 가져오지 못한 완전 실패 시 결과 영역 숨김
      if (!data.name) {
        resultContainer.classList.add("hidden");
        return;
      }

      console.log(
        `[PARSED] 기본 정보 수집 완료 (종목명: ${data.name}, 현재가: ${data.snapshot?.current_price})`
      );
      console.log(`[NEWS] 뉴스 수집 완료 (수집된 기사 수: ${data.news?.length || 0})`);

      renderResult(data);
      console.log("[RENDER] 화면 데이터 카드 렌더링 완료");
    } catch (err) {
      console.error("[ERROR] 수집 중 오류 발생:", err.message);
      renderErrors(["서버와 통신하는 중 오류가 발생했습니다. 서버가 실행 중인지 확인해 주세요."]);
      resultContainer.classList.add("hidden");
    } finally {
      loadingBox.classList.add("hidden");
      fetchBtn.disabled = false;
    }
  }

  function renderErrors(errors) {
    errorBox.innerHTML = "";
    const title = document.createElement("strong");
    title.textContent = "⚠️ 확인이 필요한 안내:";
    errorBox.appendChild(title);

    const ul = document.createElement("ul");
    errors.forEach((msg) => {
      const li = document.createElement("li");
      li.textContent = msg;
      ul.appendChild(li);
    });
    errorBox.appendChild(ul);
    errorBox.classList.remove("hidden");
  }

  function renderResult(data) {
    // 1. 종목 헤더
    document.getElementById("stock-name").textContent = data.name || "-";
    document.getElementById("stock-code-badge").textContent = data.code || "-";

    // 2. 스냅샷 카드
    const snap = data.snapshot || {};
    document.getElementById("val-price").textContent =
      snap.current_price !== null && snap.current_price !== undefined
        ? `${snap.current_price.toLocaleString("ko-KR")}원`
        : "-";

    const changeEl = document.getElementById("val-change");
    changeEl.classList.remove("up", "down");
    if (snap.change_rate !== null && snap.change_rate !== undefined) {
      const sign = snap.change_rate > 0 ? "+" : "";
      changeEl.textContent = `${sign}${snap.change_rate}%`;
      if (snap.change_rate > 0) changeEl.classList.add("up");
      else if (snap.change_rate < 0) changeEl.classList.add("down");
    } else {
      changeEl.textContent = "-";
    }

    document.getElementById("val-cap").textContent = formatKoreanCurrency(snap.market_cap);
    document.getElementById("val-per").textContent =
      snap.per !== null && snap.per !== undefined ? `${snap.per}배` : "-";
    document.getElementById("val-pbr").textContent =
      snap.pbr !== null && snap.pbr !== undefined ? `${snap.pbr}배` : "-";

    // 3. 연간 기업실적분석 테이블
    const tbody = document.getElementById("finance-tbody");
    tbody.innerHTML = "";
    const financials = data.financials || [];
    if (financials.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 5;
      td.style.textAlign = "center";
      td.textContent = "수집된 실적 데이터가 없습니다.";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      financials.forEach((row) => {
        const tr = document.createElement("tr");

        const tdPeriod = document.createElement("td");
        tdPeriod.textContent = row.period || "-";

        const tdType = document.createElement("td");
        const badge = document.createElement("span");
        if (row.is_consensus) {
          badge.className = "badge-consensus";
          badge.textContent = "추정(E)";
        } else {
          badge.className = "badge-confirmed";
          badge.textContent = "확정";
        }
        tdType.appendChild(badge);

        const tdRev = document.createElement("td");
        tdRev.textContent = formatKoreanCurrency(row.revenue);

        const tdOp = document.createElement("td");
        tdOp.textContent = formatKoreanCurrency(row.operating_income);

        const tdRoe = document.createElement("td");
        tdRoe.textContent =
          row.roe !== null && row.roe !== undefined ? `${row.roe}%` : "-";

        tr.append(tdPeriod, tdType, tdRev, tdOp, tdRoe);
        tbody.appendChild(tr);
      });
    }

    // 4. 뉴스 리스트
    const newsListEl = document.getElementById("news-list");
    newsListEl.innerHTML = "";
    const news = data.news || [];
    if (news.length === 0) {
      const li = document.createElement("li");
      li.className = "news-item";
      li.textContent = "수집된 관련 뉴스가 없습니다.";
      newsListEl.appendChild(li);
    } else {
      news.forEach((item) => {
        const li = document.createElement("li");
        li.className = "news-item";

        const a = document.createElement("a");
        a.className = "news-title";
        a.href = item.url || "#";
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = item.title || "제목 없음";

        const dateDiv = document.createElement("div");
        dateDiv.className = "news-date";
        dateDiv.textContent = item.published || "";

        const descDiv = document.createElement("div");
        descDiv.className = "news-desc";
        descDiv.textContent = item.description || "";

        li.append(a, dateDiv, descDiv);
        newsListEl.appendChild(li);
      });
    }

    resultContainer.classList.remove("hidden");
  }

  // 원(KRW) 단위 큰 숫자를 읽기 쉬운 '조/억' 단위로 포맷팅
  function formatKoreanCurrency(amount) {
    if (amount === null || amount === undefined) return "-";
    const isNegative = amount < 0;
    const absVal = Math.abs(amount);
    const eok = Math.round(absVal / 100_000_000);
    const jo = Math.floor(eok / 10_000);
    const restEok = eok % 10_000;

    let formatted = "";
    if (jo > 0) {
      formatted =
        restEok > 0
          ? `${jo.toLocaleString("ko-KR")}조 ${restEok.toLocaleString("ko-KR")}억`
          : `${jo.toLocaleString("ko-KR")}조`;
    } else {
      formatted = `${eok.toLocaleString("ko-KR")}억`;
    }
    return isNegative ? `-${formatted}` : formatted;
  }
});
