export interface DappReference {
  time?: string;
  link?: string;
}

export interface DappMetadata {
  name?: string;
  cause?: string;
  cause_zh?: string;
  platform?: string;
  platform_zh?: string;
  time?: string;
  transaction_hash?: string[];
  report?: string;
  report_zh?: string;
  background_zh?: string;
  detection?: DappReference;
  disclosure?: DappReference;
  root_cause?: string;
  root_cause_zh?: string;
  report_link?: string;
}

const dappModules = import.meta.glob("../data/*.json", { eager: true, import: "default" }) as Record<
  string,
  DappMetadata
>;

export const DAPP_CONTEXT_MAP = Object.fromEntries(
  Object.entries(dappModules).map(([path, data]) => {
    const fallbackName = path.split("/").pop()?.replace(/\.json$/, "") ?? "";
    return [data.name ?? fallbackName, data];
  }),
) as Record<string, DappMetadata>;

export function getDappMetadata(dappName?: string | null) {
  return dappName ? DAPP_CONTEXT_MAP[dappName] : undefined;
}

export function shortHash(hash: string) {
  if (hash.length <= 18) return hash;
  return `${hash.slice(0, 10)}...${hash.slice(-8)}`;
}
