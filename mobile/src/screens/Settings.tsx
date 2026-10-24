import { useState } from "react";
import type { Settings as AppSettings } from "../state";
import { normalizeOrigin } from "../state";
import { Icon } from "../components/Icon";
function Toggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <div className="setting-row">
      <div>
        <strong>{label}</strong>
        <p>{description}</p>
      </div>
      <button
        className="toggle"
        role="switch"
        aria-label={label}
        aria-checked={checked}
        onClick={onChange}
      >
        <span />
      </button>
    </div>
  );
}
export function SettingsScreen({
  settings,
  onChange,
  onTopics,
}: {
  settings: AppSettings;
  onChange: (next: AppSettings) => void;
  onTopics: () => void;
}) {
  const [origin, setOrigin] = useState(settings.origin);
  const [message, setMessage] = useState("");
  return (
    <>
      <div className="screen-title">
        <h1>설정</h1>
      </div>
      <section className="settings-group">
        <h2>읽기 설정</h2>
        <Toggle
          label="큰 글자"
          description="내용을 조금 더 크게 보여줘요."
          checked={settings.fontSize === "large"}
          onChange={() =>
            onChange({
              ...settings,
              fontSize: settings.fontSize === "large" ? "normal" : "large",
            })
          }
        />
        <Toggle
          label="움직임 줄이기"
          description="화면 전환 효과를 줄여요."
          checked={settings.reducedMotion}
          onChange={() =>
            onChange({ ...settings, reducedMotion: !settings.reducedMotion })
          }
        />
        <Toggle
          label="가벼운 진동"
          description="앱에서 저장할 때 짧게 알려줘요."
          checked={settings.haptics}
          onChange={() => onChange({ ...settings, haptics: !settings.haptics })}
        />
      </section>
      <section className="settings-group">
        <h2>나의 관심</h2>
        <button className="setting-row row-button" onClick={onTopics}>
          <div>
            <strong>관심 주제 설정</strong>
            <p>
              {settings.topics.length
                ? `${settings.topics.length}개 주제를 선택했어요.`
                : "궁금한 주제부터 시작해 보세요."}
            </p>
          </div>
          <Icon name="arrow" size={18} />
        </button>
      </section>
      <section className="settings-group">
        <h2>자료 연결</h2>
        <div className="mode-control" role="group" aria-label="자료 모드">
          <button
            aria-pressed={settings.mode === "preview"}
            onClick={() => {
              onChange({ ...settings, mode: "preview" });
              setMessage("디자인 미리보기로 전환했어요.");
            }}
          >
            디자인 미리보기
          </button>
          <button
            aria-pressed={settings.mode === "live"}
            onClick={() => {
              if (!settings.origin) {
                setMessage("아래에 HTTPS 서버 주소를 입력해 주세요.");
                return;
              }
              onChange({ ...settings, mode: "live" });
              setMessage("실제 공개 기록을 조회해요.");
            }}
          >
            실제 기록
          </button>
        </div>
        <p className="setting-help">
          미리보기는 화면 설명용 예시예요. 실제 기록 모드는 연결한 서버의 공개
          자료만 표시해요.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const valid = normalizeOrigin(origin);
            if (!valid) {
              setMessage("경로나 계정 정보가 없는 HTTPS 주소를 입력해 주세요.");
              return;
            }
            onChange({
              ...settings,
              origin: valid,
              mode: "live",
              saved: {
                ...settings.saved,
                live: valid === settings.origin ? settings.saved.live : [],
              },
            });
            setOrigin(valid);
            setMessage("서버를 연결했어요. 홈에서 기록을 확인해 주세요.");
          }}
        >
          <label className="input-label" htmlFor="origin">
            공개 API 서버 주소
          </label>
          <input
            id="origin"
            type="url"
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            placeholder="https://your-service.example"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
          />
          <button className="secondary-button wide connect-button">
            서버 연결하기 <Icon name="arrow" size={16} />
          </button>
        </form>
        <p className="form-message" role="status">
          {message}
        </p>
      </section>
      <section className="privacy-card">
        <Icon name="shield" size={25} />
        <div>
          <strong>관심은 이 기기에만.</strong>
          <p>
            관심 주제와 저장한 기록 ID는 기기에 보관해요. 로그인 정보와 정치
            성향은 수집하지 않아요.
          </p>
        </div>
      </section>
      <p className="app-version">
        의정의 흐름 · Android 0.1.0
        <br />
        공식 정부·국회 앱이 아닌 독립 서비스입니다.
      </p>
    </>
  );
}
