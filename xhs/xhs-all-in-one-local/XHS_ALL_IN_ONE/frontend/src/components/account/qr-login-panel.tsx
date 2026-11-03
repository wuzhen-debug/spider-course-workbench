import { Alert, Button, Card, Checkbox, Space, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";

import { createXhsCreatorQrLoginSession, createXhsPcQrLoginSession, pollXhsLoginSession } from "../../lib/api";
import type { PlatformAccount, XhsQrLoginSession } from "../../types";
import { loginErrorMessage, loginErrorStatus, pollLoginSequentially } from "./login-state";

const { Text, Link: AntLink } = Typography;

type QrLoginPanelProps = {
  accountType: "pc" | "creator";
  onConfirmed: (account: PlatformAccount) => void;
  targetCreatorAccountId?:number;
};

export function QrLoginPanel({ accountType, onConfirmed, targetCreatorAccountId }: QrLoginPanelProps) {
  const [session, setSession] = useState<XhsQrLoginSession | null>(null);
  const [statusText, setStatusText] = useState("准备生成二维码");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncCreator, setSyncCreator] = useState(!!targetCreatorAccountId);
  const confirmedRef = useRef(false);
  const generation = useRef(0);
  const onConfirmedRef = useRef(onConfirmed);
  onConfirmedRef.current = onConfirmed;

  async function startSession() {
    const request = ++generation.current;
    setIsLoading(true);
    setError(null);
    setSession(null);
    setStatusText("正在生成二维码");
    confirmedRef.current = false;
    try {
      const nextSession =
        accountType === "pc"
          ? await createXhsPcQrLoginSession({ sync_creator: syncCreator, target_creator_account_id:targetCreatorAccountId })
          : await createXhsCreatorQrLoginSession();
      if (generation.current !== request) return;
      setSession(nextSession);
      setStatusText(accountType === "pc" ? "请使用小红书 App 扫描二维码" : "请使用小红书 App 扫描 Creator 二维码");
    } catch (caught) {
      if (generation.current !== request) return;
      setError(loginErrorMessage(caught, "二维码生成未完成，请稍后重试。"));
      setStatusText("二维码尚未生成成功");
    } finally {
      if (generation.current === request) setIsLoading(false);
    }
  }

  useEffect(() => {
    void startSession();
    return () => { generation.current += 1; };
  }, [accountType, syncCreator,targetCreatorAccountId]);

  useEffect(() => {
    if (!session?.session_id || ["confirmed", "expired", "failed"].includes(session.status)) {
      return;
    }
    const request = generation.current;
    const sessionId = session.session_id;
    return pollLoginSequentially({
      load: () => pollXhsLoginSession(sessionId),
      onResult(polled) {
        if (generation.current !== request || polled.session_id !== sessionId) return false;
        setError(null);
        if (polled.status === "confirmed" && !polled.account) {
          setSession((current) => current ? { ...current, status: "failed" } : current);
          setStatusText("登录确认后未取得账号信息");
          setError("平台尚未返回绑定成功的账号信息，请刷新二维码后重试。");
          return false;
        }
        setSession((current) => ({
          ...polled,
          qr_image_data_url: polled.qr_image_data_url ?? current?.qr_image_data_url
        }));
        if (polled.status === "scanned") {
          setStatusText("已扫码，请在手机端确认登录");
        } else if (polled.status === "expired") {
          setStatusText("二维码已过期，请刷新");
        } else if (polled.status === "confirmed" && polled.account && !confirmedRef.current) {
          confirmedRef.current = true;
          setStatusText("账号绑定成功");
          onConfirmedRef.current(polled.account);
        } else if (polled.status === "pending") {
          setStatusText("请使用小红书 App 扫描二维码");
        }
        return !["confirmed", "expired", "failed"].includes(polled.status);
      },
      onError(caught, failures) {
        if (generation.current !== request) return false;
        const status = loginErrorStatus(caught);
        const stop = failures >= 3 || (status !== undefined && status >= 400 && status < 500 && status !== 408);
        const reason = loginErrorMessage(caught, "读取扫码登录状态未完成，请稍后重试。");
        setError(stop ? `${reason} 轮询已暂停，请刷新二维码后重试。` : reason);
        if (stop) {
          setSession((current) => current ? { ...current, status: status === 410 ? "expired" : "failed" } : current);
          setStatusText("扫码状态读取已暂停");
        }
        return !stop;
      }
    });
  }, [accountType, session?.session_id, session?.status]);

  const qrVisible = session?.qr_image_data_url && !isLoading && !["confirmed", "expired", "failed"].includes(session.status);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        styles={{
          body: {
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
            minHeight: 220,
            background: "#1f1f1f",
          },
        }}
        style={{ borderColor: "#303030" }}
      >
        {qrVisible ? (
          <img
            src={session?.qr_image_data_url}
            alt="小红书登录二维码"
            style={{ width: 180, height: 180, borderRadius: 8, background: "#fff", padding: 8 }}
          />
        ) : (
          <div
            style={{
              width: 180,
              height: 180,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "#262626",
              borderRadius: 8,
              color: "rgba(255,255,255,0.3)",
              fontSize: 28,
              fontWeight: 700,
            }}
          >
            {isLoading ? "生成中" : session?.status === "confirmed" ? "已绑定" : session?.status === "expired" ? "已过期" : "QR"}
          </div>
        )}
      </Card>

      <div style={{ textAlign: "center" }}>
        <Text strong style={{ display: "block", marginBottom: 4, color: "rgba(255,255,255,0.88)" }}>
          {statusText}
        </Text>
        {qrVisible && session?.qr_url ? (
          <AntLink href={session.qr_url} target="_blank" rel="noreferrer">
            打开二维码链接
          </AntLink>
        ) : null}
      </div>

      {accountType === "pc" ? (
        <Checkbox
          checked={syncCreator}
          disabled={isLoading||!!targetCreatorAccountId}
          onChange={(event) => setSyncCreator(event.target.checked)}
          style={{ color: "rgba(255,255,255,0.88)" }}
        >
          登录 PC 后同步 Creator 账号
        </Checkbox>
      ) : null}

      {error ? <Alert type="error" message={error} showIcon /> : null}

      <Button
        block
        icon={<ReloadOutlined />}
        onClick={startSession}
        disabled={isLoading}
        loading={isLoading}
      >
        {isLoading ? "生成中..." : "刷新二维码"}
      </Button>
    </Space>
  );
}
