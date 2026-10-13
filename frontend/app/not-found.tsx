import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-[70dvh] max-w-lg flex-col items-center justify-center gap-4 p-6 text-center">
      <p className="text-sm font-semibold text-slate-500">404</p>
      <h1 className="text-2xl font-bold">没有找到这个页面</h1>
      <p className="text-slate-600">链接可能已失效，请返回风控工作台继续浏览。</p>
      <Link href="/" className="rounded-lg bg-emerald-800 px-5 py-3 text-white">返回首页</Link>
    </main>
  );
}
