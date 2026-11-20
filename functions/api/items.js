/**
 * Cloudflare Pages Function — R2 items.json 프록시 (/api/items)
 *
 * 필수 바인딩 설정 (Cloudflare Pages > Settings > Bindings > R2 bucket):
 * - Variable name: ICONS_BUCKET
 * - R2 bucket: items.json 및 icons/*.png 가 업로드된 비공개 R2 버킷
 */
export async function onRequestGet(context) {
  const { request, env } = context;

  const bucket = env.ICONS_BUCKET;
  if (!bucket) {
    return new Response(
      JSON.stringify({
        error: "Cloudflare Pages > Settings > Bindings 에 'ICONS_BUCKET' R2 바인딩이 설정되지 않았거나 재배포가 필요합니다.",
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
        error: "R2 버킷에 'items.json' 파일이 아직 없습니다. DarkWood2 레포의 GitHub Actions 워크플로우 실행이 완료되었는지 확인해 주세요.",
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
