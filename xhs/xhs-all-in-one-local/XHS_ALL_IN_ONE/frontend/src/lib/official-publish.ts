export function officialPublishBody(body: string, topics: string[]): string {
  const tags = [...new Set(topics.map(t => t.trim().replace(/^#+/, "").trim()).filter(Boolean))];
  return body.trimEnd() + (tags.length ? `\n\n${tags.map(t => `#${t}`).join(" ")}` : "");
}
