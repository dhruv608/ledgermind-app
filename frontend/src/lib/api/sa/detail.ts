// Reads the server's error message from a failed response.

export async function detail(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : fallback;
}
