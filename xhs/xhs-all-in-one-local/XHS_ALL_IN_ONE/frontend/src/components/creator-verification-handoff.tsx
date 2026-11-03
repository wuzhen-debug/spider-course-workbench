import { QrcodeOutlined, ReloadOutlined } from "@ant-design/icons";
import { Button, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { acknowledgeCreatorVerification, fetchCreatorVerification } from "../lib/api";
import type { CreatorVerification } from "../lib/api";

export function CreatorVerificationHandoff({jobId, publishError}: {jobId: number; publishError: string}) {
  const [result, setResult] = useState<CreatorVerification | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [acknowledging, setAcknowledging] = useState(false);
  const [ackError, setAckError] = useState("");
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setResult(null);
    setAckError("");
    fetchCreatorVerification(jobId).then(value => {
      if (!cancelled) setResult(value);
    }).catch(() => {
      if (!cancelled) setResult({job_id: jobId, state: "unavailable", automatic_retry: false, will_publish: false,
        message: "验证入口读取失败，请刷新入口。未重新提交笔记。"});
    }).finally(() => {if (!cancelled) setLoading(false);});
    return () => {cancelled = true;};
  }, [jobId, publishError, revision]);

  async function acknowledge() {
    if (!result?.task_id || acknowledging) return;
    setAcknowledging(true); setAckError("");
    try {setResult(await acknowledgeCreatorVerification(jobId, result.task_id));}
    catch {setAckError("记录未保存，请刷新验证入口。未提交笔记。");}
    finally {setAcknowledging(false);}
  }

  // URLs come from the authenticated local endpoint. Also constrain them here
  // so this recovery action can only navigate to the official captcha page.
  let url: string | undefined;
  if (result?.job_id === jobId && result.official_url) {
    try {
      const parsed = new URL(result.official_url);
      if (parsed.origin === "https://www.xiaohongshu.com" && parsed.pathname === "/web-login/captcha") url = parsed.href;
    } catch { /* no navigation for invalid URLs */ }
  }
  return <Space direction="vertical" size={8}>
    <Typography.Text>{loading ? "正在读取本次验证入口…" : `${result?.account_name ? `账号：${result.account_name}。` : ""}${result?.message || "当前没有可恢复的验证请求。"}`}</Typography.Text>
    <Space wrap>
      {url && <Button type="primary" size="small" icon={<QrcodeOutlined />} href={url}
        target="_blank" rel="noopener noreferrer">
        {result?.state === "available" ? "扫码处理本次验证" : "打开官方扫码验证"}
      </Button>}
      {url && result?.task_id && <Button size="small" loading={acknowledging} onClick={acknowledge}>我已在手机完成验证</Button>}
      {!["legacy_missing", "not_required", "reported_verified"].includes(result?.state || "") && <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={() => setRevision(v => v + 1)}>刷新验证入口</Button>}
    </Space>
    {ackError && <Typography.Text type="danger">{ackError}</Typography.Text>}
  </Space>;
}
