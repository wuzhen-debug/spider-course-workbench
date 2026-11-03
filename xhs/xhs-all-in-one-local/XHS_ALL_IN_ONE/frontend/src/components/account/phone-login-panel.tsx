import { Alert, Button, Checkbox, Form, Input, Space, Typography } from "antd";
import { MessageOutlined, CheckCircleOutlined } from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";

import { confirmXhsPhoneLogin, sendXhsPhoneCode } from "../../lib/api";
import type { PlatformAccount } from "../../types";
import { loginErrorMessage, loginErrorStatus } from "./login-state";

const { Text } = Typography;

type PhoneLoginPanelProps = {
  accountType: "pc" | "creator";
  onConfirmed: (account: PlatformAccount) => void;
};

const PHONE_CODE_COOLDOWN_SECONDS = 120;

export function PhoneLoginPanel({ accountType, onConfirmed }: PhoneLoginPanelProps) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [sessionPhone, setSessionPhone] = useState("");
  const [statusText, setStatusText] = useState("输入手机号后发送验证码");
  const [isSending, setIsSending] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [syncCreator, setSyncCreator] = useState(false);
  const generation = useRef(0);
  const busy = useRef(false);
  const isCoolingDown = cooldownSeconds > 0;

  useEffect(() => () => { generation.current += 1; }, []);

  useEffect(() => {
    if (cooldownSeconds <= 0) {
      return;
    }

    const timer = window.setTimeout(() => {
      setCooldownSeconds((current) => Math.max(0, current - 1));
    }, 1000);

    return () => window.clearTimeout(timer);
  }, [cooldownSeconds]);

  async function handleSendCode() {
    if (busy.current || isCoolingDown) {
      return;
    }
    setError(null);
    if (phone.trim().length < 6) {
      setError("请输入有效手机号。");
      return;
    }

    const request = ++generation.current;
    const requestedPhone = phone.trim();
    busy.current = true;
    setSessionId(null);
    setSessionPhone("");
    setCode("");
    setIsSending(true);
    try {
      const result = await sendXhsPhoneCode({
        sub_type: accountType,
        phone: requestedPhone,
        sync_creator: accountType === "pc" ? syncCreator : undefined
      });
      if (generation.current !== request) return;
      setSessionId(result.session_id);
      setSessionPhone(requestedPhone);
      setStatusText("验证码已发送，请查看手机短信");
      setCooldownSeconds(PHONE_CODE_COOLDOWN_SECONDS);
    } catch (caught) {
      if (generation.current !== request) return;
      setError(loginErrorMessage(caught, "验证码发送未完成，请稍后重试。"));
      setStatusText("验证码尚未发送成功");
    } finally {
      if (generation.current === request) {
        busy.current = false;
        setIsSending(false);
      }
    }
  }

  async function handleConfirm() {
    if (busy.current) return;
    setError(null);
    if (!sessionId || sessionPhone !== phone.trim()) {
      setError("请先发送验证码。");
      return;
    }
    if (code.trim().length < 4) {
      setError("请输入短信验证码。");
      return;
    }

    const request = ++generation.current;
    busy.current = true;
    setIsConfirming(true);
    try {
      const result = await confirmXhsPhoneLogin({
        sub_type: accountType,
        session_id: sessionId,
        phone: phone.trim(),
        code: code.trim(),
        sync_creator: accountType === "pc" ? syncCreator : undefined
      });
      if (generation.current !== request) return;
      if (result.status !== "confirmed" || !result.account) {
        setError("平台尚未返回绑定成功的账号信息，请检查手机端提示后重试。");
        return;
      }
      setStatusText("账号绑定成功");
      setCode("");
      setSessionId(null);
      setSessionPhone("");
      onConfirmed(result.account);
    } catch (caught) {
      if (generation.current !== request) return;
      setError(loginErrorMessage(caught, "账号绑定未完成，请检查手机端提示后重试。"));
      if ([404, 410].includes(loginErrorStatus(caught) ?? 0)) {
        setSessionId(null);
        setSessionPhone("");
        setCode("");
        setStatusText("登录会话已失效，请重新发送验证码");
      }
    } finally {
      if (generation.current === request) {
        busy.current = false;
        setIsConfirming(false);
      }
    }
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Text style={{ color: "rgba(255,255,255,0.65)" }}>{statusText}</Text>

      <Form layout="vertical">
        <Form.Item label={<span style={{ color: "rgba(255,255,255,0.88)" }}>手机号</span>}>
          <Input
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value);
              setSessionId(null);
              setSessionPhone("");
              setCode("");
              setError(null);
              setStatusText("输入手机号后发送验证码");
            }}
            disabled={isSending || isConfirming}
            maxLength={32}
            inputMode="tel"
            autoComplete="tel"
            placeholder="请输入手机号"
            style={{ background: "#1f1f1f", borderColor: "#303030", color: "rgba(255,255,255,0.88)" }}
          />
        </Form.Item>
      </Form>

      {accountType === "pc" ? (
        <Checkbox
          checked={syncCreator}
          disabled={isSending || isConfirming}
          onChange={(event) => setSyncCreator(event.target.checked)}
          style={{ color: "rgba(255,255,255,0.88)" }}
        >
          登录 PC 后同步 Creator 账号
        </Checkbox>
      ) : null}

      <Button
        block
        icon={<MessageOutlined />}
        onClick={handleSendCode}
        disabled={isSending || isConfirming || isCoolingDown}
        loading={isSending}
      >
        {isSending ? "发送中..." : isCoolingDown ? `${cooldownSeconds} 秒后重发` : "发送验证码"}
      </Button>

      <Form layout="vertical">
        <Form.Item label={<span style={{ color: "rgba(255,255,255,0.88)" }}>验证码</span>}>
          <Input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            disabled={isSending || isConfirming || !sessionId}
            maxLength={12}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="请输入验证码"
            style={{ background: "#1f1f1f", borderColor: "#303030", color: "rgba(255,255,255,0.88)" }}
          />
        </Form.Item>
      </Form>

      {error ? <Alert type="error" message={error} showIcon /> : null}

      <Button
        type="primary"
        block
        icon={<CheckCircleOutlined />}
        onClick={handleConfirm}
        disabled={isSending || !sessionId || sessionPhone !== phone.trim() || code.trim().length < 4}
        loading={isConfirming}
      >
        {isConfirming ? "验证中..." : "确认绑定"}
      </Button>
    </Space>
  );
}
