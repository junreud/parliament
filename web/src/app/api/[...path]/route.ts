import { forwardApi } from "@/lib/proxy";
export const dynamic = "force-dynamic";
async function handle(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forwardApi(request, path);
}
export { handle as GET, handle as POST, handle as PUT };
