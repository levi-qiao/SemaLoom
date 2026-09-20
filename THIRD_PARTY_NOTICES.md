# Third-party notices

The complete license texts for packages included in the current Studio bundle,
including react-markdown and its dependencies, are generated during the frontend
build in `src/semaloom/app/static/third-party-licenses.txt` and served at
`/studio/third-party-licenses.txt`.

The optional Chat worker uses the MIT-licensed official
[@earendil-works/pi-agent-core and pi-ai](https://github.com/earendil-works/pi).
Their pinned npm distributions retain their own license files; the Python wheel
ships only SemaLoom's worker and dependency manifest, not installed npm packages.

SemaLoom Studio's compiled browser assets include the following packages:

- React 19.3.0
- React DOM 19.3.0
- Scheduler 0.28.0

Copyright (c) Meta Platforms, Inc. and affiliates.

These packages are distributed under the MIT License:

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

The source and license information for these packages is available from the
[React repository](https://github.com/facebook/react).

Studio's optional, lazily loaded graph layout includes `elkjs 0.12.0`, used
under the Eclipse Public License 2.0. The unmodified source is available from
the [ELK.js project](https://github.com/kieler/elkjs) and the versioned
[elkjs npm distribution](https://www.npmjs.com/package/elkjs/v/0.12.0).
Its complete license is included in `/studio/third-party-licenses.txt`.

Chat's optional, lazily loaded result presentation includes
`@json-render/core 0.21.0` and `@json-render/react 0.21.0` under Apache-2.0,
plus `recharts 3.10.1` and `zod 4.3.6` under MIT. The catalog is restricted to
SemaLoom-owned deterministic result modules; these packages do not receive
database credentials or add a network service. Complete upstream license texts
are generated into `/studio/third-party-licenses.txt` with the browser bundle.
