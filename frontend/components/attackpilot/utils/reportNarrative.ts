import { compactEvidenceText } from "./evidence";

interface NarrativeParagraph {
  heading: string;
  content: string;
}

// These sections describe verification, proposed changes or report metadata;
// their words such as "execution", "state" and "profit" are not attack steps.
const excludedHeading = /^(?:补丁验证(?:状态|结果)?|验证(?:状态|结果|范围)|回放(?:结果|证据)|执行证据|实际应用补丁|补丁建议|修复建议|价格证据|任务信息|智能体证据摘要|参考资料|风险与限制|applied\s+patches|(?:patch\s+)?verification(?:\s+(?:status|results?|summary))?|validation(?:\s+results?)?|replay\s+(?:results?|evidence)|patch(?:\s+(?:suggestions?|recommendations?|code))?|mitigation(?:s|\s+suggestions?)?|price\s+evidence|task\s+(?:information|metadata)|agent\s+(?:evidence|summary)|references|limitations)(?:\s|[:：（(]|$)/i;

function headingOf(line: string) {
  const markdown = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
  const plain = line.match(/^\s*(?:\*\*)?\d+(?:\.\d+)*[.)、]\s+(.+?)(?:\*\*)?\s*$/);
  if (!markdown && !plain) return null;
  const title = (markdown?.[2] ?? plain![1]).replace(/^\*+|\*+$/g, "")
    .replace(/^\d+(?:\.\d+)*[.)、]?\s+/, "").trim();
  // A numbered sentence is usually a list item, not a report heading.
  const narrativeHeading = /^(?:漏洞根因|根因|攻击准备|攻击前置条件|漏洞触发|攻击路径|攻击流程|状态操纵|价格操纵|攻击获利|资产转移|root cause|attack preparation|preparation|setup|trigger|attack path|attack flow|exploit path|state manipulation|price manipulation|profit|fund flow)[:：]?$/i;
  if (!markdown && !excludedHeading.test(title) && !narrativeHeading.test(title)) return null;
  return { title, level: markdown?.[1].length ?? 2 };
}

/** Keep attack prose separate from machine status tables and patch code. */
export function reportNarrativeParagraphs(report: string): NarrativeParagraph[] {
  const lines = report.split(/\r?\n/);
  const tableRows = new Set<number>();
  const separator = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;
  lines.forEach((line, index) => {
    if (!separator.test(line)) return;
    if (index > 0 && lines[index - 1].includes("|")) tableRows.add(index - 1);
    for (let row = index; row < lines.length && lines[row].includes("|"); row += 1) tableRows.add(row);
  });
  const paragraphs: NarrativeParagraph[] = [];
  let heading = "", excludedLevel: number | null = null;
  let fence: { marker: string; length: number } | null = null;
  let current: string[] = [];
  const flush = () => {
    const content = current.join("\n").trim();
    if (content) paragraphs.push({ heading, content });
    current = [];
  };
  lines.forEach((line, index) => {
    const marker = line.match(/^\s{0,3}(`{3,}|~{3,})/);
    if (marker) {
      flush();
      if (!fence) fence = { marker: marker[1][0], length: marker[1].length };
      else if (fence.marker === marker[1][0] && marker[1].length >= fence.length) fence = null;
      return;
    }
    if (fence) return;
    const section = headingOf(line);
    if (section) {
      flush();
      if (excludedLevel !== null && section.level <= excludedLevel) excludedLevel = null;
      if (excludedLevel === null && excludedHeading.test(section.title)) excludedLevel = section.level;
      heading = section.title;
      return;
    }
    if (excludedLevel !== null || tableRows.has(index) || /^\s*\|/.test(line)) { flush(); return; }
    if (!line.trim()) flush();
    else current.push(line);
  });
  flush();
  return paragraphs;
}

export function findNarrativeSummary(report: string, keywords: string[], fallback: string,
                                     limit = 360, headings: string[] = []) {
  const paragraphs = reportNarrativeParagraphs(report);
  const hasKeyword = (paragraph: NarrativeParagraph) => keywords.some(keyword => paragraph.content.toLowerCase().includes(keyword.toLowerCase()));
  const preferred = paragraphs.filter(paragraph => headings.some(title => paragraph.heading.toLowerCase().includes(title.toLowerCase())));
  const match = preferred.find(hasKeyword) ?? preferred[0] ?? paragraphs.find(hasKeyword);
  return match ? compactEvidenceText(match.content, limit) : fallback;
}
