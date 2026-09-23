import { handle } from './_shared/yahoo-core.mjs';
declare const Netlify: { env: { get(name: string): string | undefined } };
export default (request: Request) => handle('callback', request, { env: name => Netlify.env.get(name) });
