export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET',
        },
      });
    }

    if (request.method !== 'GET') {
      return new Response('Method not allowed', { status: 405 });
    }

    const parts = new URL(request.url).pathname.split('/').filter(Boolean);
    if (parts.length !== 2) {
      return new Response('Expected /{submodule}/{filename}', { status: 400 });
    }

    const [submodule, filename] = parts;

    if (!/^[A-Za-z]\d{2}$/.test(submodule) || !/^[A-Za-z]\d{3,}\.xml$/.test(filename)) {
      return new Response('Invalid path', { status: 400 });
    }

    const upstream = await fetch(
      `https://bitbucket.org/eads004/${submodule}/raw/master/${filename}`
    );

    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        'Content-Type': 'application/xml; charset=utf-8',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'public, max-age=86400',
      },
    });
  },
};
