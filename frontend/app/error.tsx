"use client";

import Link from "next/link";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="flex min-h-[70dvh] items-center justify-center p-6">
      <section role="alert" className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-bold">页面暂时无法显示</h1>
        <p className="mt-3 text-sm leading-6 text-slate-600">请重试加载，或返回首页继续操作。若问题持续出现，请保留当前页面地址以便排查。</p>
        <div className="mt-6 flex gap-4">
          <button type="button" onClick={reset} className="rounded-lg bg-emerald-800 px-4 py-2 text-white">重新加载</button>
          <Link href="/" className="rounded-lg border border-slate-300 px-4 py-2">返回首页</Link>
        </div>
      </section>
    </main>
  );
}
