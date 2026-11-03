import { useEffect, useState } from "react";
import { Alert, Button, Modal, Space, Typography } from "antd";
import { CopyOutlined, DownloadOutlined, ExportOutlined } from "@ant-design/icons";
import { downloadOfficialPublishPackage } from "../lib/api";
import { officialPublishBody } from "../lib/official-publish";
import type { PublishJob } from "../types";

const { Paragraph, Text } = Typography;

export function OfficialPublishHandoff({open, job, topics, imageCount, onClose}: {
  open: boolean; job: PublishJob | null; topics: string[]; imageCount: number; onClose: () => void;
}) {
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<"title" | "body" | null>(null);
  useEffect(() => { setDownloaded(false); setError(null); setCopied(null); }, [open, job?.id]);
  async function copy(kind: "title" | "body", text: string) {
    setError(null);
    try { await navigator.clipboard.writeText(text); setCopied(kind); }
    catch { setError("浏览器未允许复制，请从准备包的文案.txt复制对应内容。"); }
  }
  async function download() {
    if (!job || downloading) return;
    setDownloading(true); setError(null);
    try { await downloadOfficialPublishPackage(job.id, topics); setDownloaded(true); }
    catch (e) { setError(e instanceof Error ? e.message : "准备包下载失败，请重试。"); }
    finally { setDownloading(false); }
  }
  return <Modal title="转到官方发布" open={open} onCancel={onClose}
    footer={<Button onClick={onClose}>关闭</Button>} width={720}>
    {job && <Space direction="vertical" size={16} style={{width:"100%"}}>
      <Text type="secondary">下载图片、复制文案后，在官方页面上传并核对。最后发布由你手动确认，原稿与任务记录保留。</Text>
      {error && <Alert type="error" title={error} showIcon/>}
      <Space wrap>
        <Button type="primary" icon={<DownloadOutlined/>} onClick={download} loading={downloading} disabled={!imageCount}>
          下载文案与{imageCount}张原图
        </Button>
        {downloaded && <Text type="success">准备包已生成，图片按01、02…顺序排列</Text>}
      </Space>
      <div><Space><Text strong>标题</Text><Button size="small" icon={<CopyOutlined/>} onClick={()=>copy("title",job.title)}>{copied==="title"?"标题已复制":"复制标题"}</Button></Space><Paragraph style={{marginTop:8}}>{job.title}</Paragraph></div>
      <div><Space><Text strong>正文与话题</Text><Button size="small" icon={<CopyOutlined/>} onClick={()=>copy("body",officialPublishBody(job.body,topics))}>{copied==="body"?"正文与话题已复制":"复制正文与话题"}</Button></Space><Paragraph
        style={{marginTop:8,maxHeight:260,overflowY:"auto",whiteSpace:"pre-wrap"}}>{officialPublishBody(job.body,topics)}</Paragraph></div>
      <Button icon={<ExportOutlined/>} href="https://creator.xiaohongshu.com/publish/publish" target="_blank" rel="noopener noreferrer">打开官方发布页</Button>
    </Space>}
  </Modal>;
}
