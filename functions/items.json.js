/**
 * Cloudflare Pages Function — R2 items.json 프록시 (/items.json)
 *
 * 필수 바인딩 설정 (Cloudflare Pages > Settings > Bindings > R2 bucket):
 * - Variable name: ICONS_BUCKET
 * - R2 bucket: items.json 및 icons/*.png 가 업로드된 비공개 R2 버킷
 *
 * Git 레포지토리(Public)에 items.json을 커밋하지 않고도
 * Cloudflare Access 인증을 통과한 사용자에게만 최신 items.json을 서빙합니다.
 */
export async function onRequestGet(context) {
  const { request, env } = context;

  const bucket = env.ICONS_BUCKET;
  if (!bucket) {
    return new Response(
      JSON.stringify({
        error: "R2 Bucket binding 'ICONS_BUCKET' is not configured in Cloudflare Pages Settings > Bindings.",
      }),
      {
        status: 503,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      }
    );
  }

  const object = await bucket.get("items.json");
  if (!object) {
    return new Response(
      JSON.stringify({
        error: "items.json not found in R2 bucket. Run the DarkWood2 GitHub Actions workflow to upload items.json to R2.",
      }),
      {
        status: 404,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      }
    );
  }

  const ifNoneMatch = request.headers.get("If-None-Match");
  if (ifNoneMatch && object.httpEtag && ifNoneMatch === object.httpEtag) {
    return new Response(null, {
      status: 304,
      headers: {
        ETag: object.httpEtag,
      },
    });
  }

  const headers = new Headers();
  headers.set("Content-Type", "application/json; charset=utf-8");
  headers.set("Cache-Control", "no-cache, must-revalidate");
  if (object.httpEtag) {
    headers.set("ETag", object.httpEtag);
  }

  return new Response(object.body, {
    status: 200,
    headers,
  });
}
