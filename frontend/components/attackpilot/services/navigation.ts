import { useCallback } from "react";
import { useRouter } from "next/navigation";
export { useParams } from "next/navigation";

export function useNavigate() {
  const router = useRouter();
  return useCallback((path: string) => {
    const mapped = path === "/learning" ? "/knowledge" : path;
    router.push(`/attackpilot${mapped === "/" ? "" : mapped}`);
  }, [router]);
}
