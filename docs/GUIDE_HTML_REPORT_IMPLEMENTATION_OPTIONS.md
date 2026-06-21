# Guide HTML Report 구현 방안

## 배경

현재 `relationship-map` 도메인은 `htmlReport`에 **완성형 HTML 문서**를 넣어 반환한다.

확인 위치:

- `model_server/domains/relationship_map/service.py`
  - `includeHtml=true`일 때 `result["htmlReport"] = build_relation_html(...)`
- `model_server/domains/relationship_map/relationship_html.py`
  - `<!doctype html>`
  - `<html lang="ko">`
  - `<head>`
  - `<style>...</style>`
  - `<body>...</body>`

즉 관계도는 현재 다음 구조다.

```txt
FastAPI relationship-map
  → data
  → htmlReport: CSS 포함 완성형 HTML
```

가이드도 원래 의도대로라면 이와 비슷하게 **모델서버가 HTML 구조와 CSS를 함께 만들어서 내려주고**, 프론트는 `htmlReport`를 렌더링하는 방식으로 맞출 수 있다.

현재 guide 쪽은 `htmlReport`를 만들고 있지만, relationship-map처럼 항상 `<style>`까지 포함한 완성형 문서로 고정되어 있지는 않다.

---

## 방안 A. 관계도와 동일한 완성형 HTML 문서 방식

### 개념

가이드 `htmlReport`를 relationship-map과 같은 방식으로 만든다.

```json
{
  "htmlReport": "<!doctype html><html lang=\"ko\"><head><style>...</style></head><body>...</body></html>"
}
```

### 예시 구조

```html
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>일본 현지화 가이드</title>
  <style>
    :root {
      --bg: #fff8fb;
      --panel: #ffffff;
      --text: #241528;
      --muted: #73606f;
      --accent: #d94697;
    }

    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", sans-serif;
      background: radial-gradient(circle at top left, #fff0fa, #fff8fb 38%, #f8fbff);
      color: var(--text);
    }

    .wl-guide-page {
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }

    .wl-guide-hero {
      background: linear-gradient(135deg, #7c2d8a, #ec4899);
      color: white;
      border-radius: 28px;
      padding: 34px;
    }
  </style>
</head>
<body>
  <main class="wl-guide-page">
    <section class="wl-guide-hero">
      <h1>일본 현지화 가이드</h1>
      <p>작품의 시장 적합성과 문화 리스크를 요약합니다.</p>
    </section>

    <section class="wl-guide-section">
      <h2>시장 해석</h2>
      <ul>
        <li>플랫폼 독자층에 맞춰 제목과 후킹 문장을 조정합니다.</li>
      </ul>
    </section>
  </main>
</body>
</html>
```

### 장점

- relationship-map과 구조가 가장 일관된다.
- 프론트는 `htmlReport`를 그대로 출력하면 된다.
- CSS 의존성이 프론트에 없다.
- 저장된 `htmlReport`만 있으면 나중에 단독 미리보기, PDF 변환, S3 저장에 유리하다.
- 모델서버 산출물이 “완성된 리포트”라는 의미가 명확하다.

### 단점

- Django/React 페이지 내부에 `html`, `head`, `body`가 들어가면 DOM 구조가 어색해질 수 있다.
- 프론트에서 `dangerouslySetInnerHTML` 또는 iframe 처리가 필요할 수 있다.
- `<style>`이 페이지 전체 CSS에 영향을 줄 수 있으므로 클래스 prefix와 CSS scope가 중요하다.
- 보안 필터링 정책이 필요하다.

### 프론트 렌더링 추천

완성형 HTML 문서 방식이면 프론트는 두 가지 중 하나를 택한다.

#### A-1. iframe 렌더링

가장 안전하다.

```html
<iframe srcdoc="htmlReport 내용"></iframe>
```

장점:

- CSS 충돌이 거의 없다.
- `html`, `head`, `body` 포함 문서와 잘 맞는다.

단점:

- iframe 높이 자동 조절 처리가 필요하다.
- 내부 클릭/스크롤 제어가 조금 번거롭다.

#### A-2. 직접 삽입

```tsx
<div dangerouslySetInnerHTML={{ __html: htmlReport }} />
```

장점:

- 구현이 쉽다.

단점:

- 전체 HTML 문서를 div 안에 넣는 형태라 구조상 부자연스럽다.
- CSS 충돌 가능성이 있다.

### 이 방안이 맞는 경우

- 관계도와 guide를 같은 출력 철학으로 맞추고 싶을 때
- 프론트가 리포트 디자인을 거의 건드리지 않을 때
- PDF/export/저장/공유 가능한 독립 문서가 중요할 때

---

## 방안 B. CSS 포함 HTML Fragment 방식

### 개념

`html`, `head`, `body`까지 포함하지 않고, 프론트 페이지 안에 삽입 가능한 조각으로 반환한다.

단, CSS는 함께 포함한다.

```json
{
  "htmlReport": "<style>...</style><div class=\"wl-guide-report\">...</div>"
}
```

### 예시 구조

```html
<style>
  .wl-guide-report {
    --wl-guide-bg: #fff8fb;
    --wl-guide-panel: #ffffff;
    --wl-guide-text: #241528;
    --wl-guide-muted: #73606f;
    --wl-guide-accent: #d94697;

    max-width: 1120px;
    margin: 0 auto;
    padding: 32px 20px 48px;
    color: var(--wl-guide-text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", sans-serif;
  }

  .wl-guide-report * {
    box-sizing: border-box;
  }

  .wl-guide-hero {
    background: linear-gradient(135deg, #7c2d8a, #ec4899);
    color: white;
    border-radius: 28px;
    padding: 34px;
  }

  .wl-guide-section {
    margin-top: 18px;
    background: rgba(255, 255, 255, .9);
    border: 1px solid #f0ddea;
    border-radius: 22px;
    padding: 20px;
  }
</style>

<div class="wl-guide-report">
  <section class="wl-guide-hero">
    <h1>일본 현지화 가이드</h1>
    <p>작품의 시장 적합성과 문화 리스크를 요약합니다.</p>
  </section>

  <section class="wl-guide-section">
    <h2>시장 해석</h2>
    <ul class="wl-guide-list">
      <li>플랫폼 독자층에 맞춰 제목과 후킹 문장을 조정합니다.</li>
    </ul>
  </section>
</div>
```

### 장점

- 프론트 페이지 안에 삽입하기 쉽다.
- `html/head/body` 중첩 문제가 없다.
- CSS도 모델서버가 같이 내려주므로 프론트 CSS 파일 추가가 필수는 아니다.
- relationship-map의 “CSS 포함 산출물” 철학은 유지하면서 웹 페이지 삽입 안정성이 높다.
- `wl-guide-*` prefix를 쓰면 CSS 충돌을 줄일 수 있다.

### 단점

- 완전한 독립 HTML 문서는 아니므로 단독 파일 저장/미리보기 시 wrapper가 필요하다.
- `<style>` 태그를 프론트에서 허용해야 한다.
- 프론트 sanitizer가 `<style>`을 제거하면 디자인이 사라진다.

### 프론트 렌더링 추천

```tsx
<div className="guide-html" dangerouslySetInnerHTML={{ __html: htmlReport }} />
```

단, sanitizer 정책에서 다음은 허용해야 한다.

- `style` 태그
- `class` 속성
- `section`, `article`, `div`, `h1`, `h2`, `h3`, `p`, `ul`, `li`, `table` 등 기본 태그

그리고 다음은 금지한다.

- `script`
- `iframe`
- `object`
- `embed`
- `form`
- `input`
- `button`
- `onload`, `onclick`, `onerror` 등 이벤트 속성
- `javascript:` URL

### 이 방안이 맞는 경우

- guide 결과를 Django/React 페이지 안에 자연스럽게 끼워 넣고 싶을 때
- iframe 없이 바로 렌더링하고 싶을 때
- CSS까지 모델서버가 책임지되 프론트 DOM 구조를 망가뜨리고 싶지 않을 때

---

## 관계도 방식 참고 결론

관계도는 현재 **방안 A**에 가깝다.

```txt
relationship-map
  includeHtml=true
  → htmlReport = <!doctype html> + <style> + body
```

guide는 현재 완성형 문서가 아니라, 일부 `htmlReport` fragment와 context pack HTML 조각이 섞여 있다.

따라서 guide를 relationship-map과 맞추려면 다음 중 하나를 선택해야 한다.

---

## 추천안

### 현재 프로젝트 기준 추천: 방안 A

이미 `relationship-map`이 **방안 A: CSS 포함 완성형 HTML 문서**를 `htmlReport`로 반환하고 있다.

따라서 guide도 같은 계약으로 맞추는 것이 가장 일관적이다.

```txt
relationship-map htmlReport = <!doctype html> + <style> + body
guide htmlReport            = <!doctype html> + <style> + body
```

이렇게 맞추면 프론트는 도메인별로 다른 렌더링 방식을 고민하지 않아도 된다.

```txt
모든 AI 리포트 htmlReport는 완성형 HTML 문서로 보고 iframe srcdoc으로 렌더링
```

### 방안 B는 언제 선택할 수 있나

방안 B를 쓰려면 guide만 바꾸는 것이 아니라 relationship-map도 같은 fragment 방식으로 바꾸는 편이 맞다.

```txt
relationship-map = CSS 포함 fragment
guide            = CSS 포함 fragment
```

하지만 현재는 relationship-map이 이미 full document 방식이므로, 지금 시점에서 방안 B로 가면 오히려 출력 계약이 갈라진다.

---

## 구현 작업 목록

### 공통

- guide 전용 renderer 추가
  - 예: `model_server/domains/guide/guide_html.py`
- 클래스 prefix 통일
  - `wl-guide-report`
  - `wl-guide-hero`
  - `wl-guide-section`
  - `wl-guide-card`
  - `wl-guide-chip`
  - `wl-guide-list`
- 기존 `htmlReport` 생성부를 새 renderer로 통일
- `docs/API_CONTRACT.md`에 `htmlReport` 형식 명시
- 테스트에서 `htmlReport`에 `<style>`과 `wl-guide-report`가 있는지 확인

### 방안 A 구현 시

- `build_guide_html_document(...)` 추가
- 반환값은 `<!doctype html>`로 시작
- `<head><style>...</style></head>` 포함
- 프론트는 iframe `srcdoc` 사용 권장

### 방안 B 구현 시

- `build_guide_html_fragment(...)` 추가
- 반환값은 `<style>` + `<div class="wl-guide-report">`
- 모든 CSS selector는 `.wl-guide-report ...` 또는 `.wl-guide-*` prefix로 제한
- 프론트는 기존 `dangerouslySetInnerHTML` 방식으로 출력 가능

---

## 최종 판단

현재 팀 상황에서는 **방안 A를 구현**하는 것이 좋다.

이유:

1. relationship-map이 이미 full HTML document 방식이다.
2. guide도 같은 `htmlReport` 렌더링 정책을 쓸 수 있다.
3. 기존 `novel_model`의 guide에도 CSS 포함 full HTML report 양식이 있다.
4. PDF/export/S3 저장/단독 미리보기에 유리하다.
5. 프론트는 `htmlReport`를 iframe `srcdoc`으로 공통 처리하면 된다.
