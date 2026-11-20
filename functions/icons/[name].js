/**
 * Cloudflare Pages Function — R2 아이콘 프록시 (/icons/:name)
 *
 * 필수 바인딩 설정 (Cloudflare Pages > Settings > Bindings > R2 bucket):
 * - Variable name: ICONS_BUCKET
 * - R2 bucket: 아이콘이 업로드된 비공개 R2 버킷
 *
 * 이 엔드포인트는 Cloudflare Pages 도메인 내부 경로(/icons/<spriteName>.png?v=<hash>)로
 * 서빙되므로, Cloudflare Access 이메일 인증 뒤에서 안전하게 보호됩니다.
 */
export async function onRequestGet(context) {
  const { request, env, params } = context;
  const rawName = params.name;

  if (!rawName || typeof rawName !== "string" || rawName.includes("..") || rawName.includes("/")) {
    return new Response("Invalid icon file name", { status: 400 });
  }

  const bucket = env.ICONS_BUCKET;
  if (!bucket) {
    return new Response(
      "R2 Bucket binding 'ICONS_BUCKET' is not configured in Cloudflare Pages Settings > Bindings.",
      { status: 503 }
    );
  }

  const fileName = decodeURIComponent(rawName);
  const primaryKey = `icons/${fileName}`;

  let object = await bucket.get(primaryKey);
  if (!object) {
    // 버킷 루트에 바로 업로드된 경우를 위한 폴백
    object = await bucket.get(fileName);
  }

  if (!object) {
    return new Response(`Icon not found: ${primaryKey}`, { status: 404 });
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

  const url = new URL(request.url);
  const hasVersionParam = url.searchParams.has("v");

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "image/png");
  }
  if (object.httpEtag) {
    headers.set("ETag", object.httpEtag);
  }

  // ?v=<hash> 쿼리가 있으면 장기 캐싱, 없으면 1시간 캐싱
  headers.set(
    "Cache-Control",
    hasVersionParam ? "public, max-age=31536000, immutable" : "public, max-age=3600"
  );

  return new Response(object.body, {
    status: 200,
    headers,
  });
}
