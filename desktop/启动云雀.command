#!/bin/zsh -l
set -e
cd "${0:A:h}"
if ! command -v node >/dev/null 2>&1; then
  for runtime in "$HOME"/.nvm/versions/node/*/bin(N/On); do
    if [[ -x "$runtime/node" ]]; then export PATH="$runtime:$PATH"; break; fi
  done
fi
if ! command -v npm >/dev/null 2>&1; then
  print '请先安装 Node.js 22.12 或更新版本，再启动云雀。'
  read 'reply?按回车键关闭。'
  exit 1
fi
if [[ ! -d node_modules/electron ]]; then npm install; fi
exec npm start
