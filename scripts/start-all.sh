#!/usr/bin/env bash
# =============================================================================
# 截流获客产品 —— 一键启动脚本
#
# 功能：
#   1. 杀掉已存在的前端 / 后端 API / Worker 进程（按端口 + 按进程名双重清理）
#   2. 重新启动三大服务：
#        - 后端 API    : AutoMarketing/run.py      (uvicorn,  :8000)
#        - 后端 Worker : AutoMarketing/worker.py   (任务轮询)
#        - 前端        : naive-ui-admin (vite,     :8001)
#   3. 健康检查并输出访问地址
#
# 用法：
#   ./scripts/start-all.sh            # 重启全部服务
#   ./scripts/start-all.sh --kill     # 仅停止全部服务
#   ./scripts/start-all.sh --no-fe    # 只启动后端（API + Worker）
#   ./scripts/start-all.sh --no-be    # 只启动前端
# =============================================================================

set -u
set -o pipefail

# ----------------------------- 路径配置 -----------------------------
FE_DIR="/Users/hyj/Documents/mywork/naive-ui-admin"
BE_DIR="/Users/hyj/Documents/mywork/AutoMarketing"
LOG_DIR="${BE_DIR}/log"
PY_VENV="${BE_DIR}/.venv312"

API_PORT=8000
FE_PORT=8001

mkdir -p "${LOG_DIR}"

# ----------------------------- 颜色输出 -----------------------------
C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_RED='\033[31m'; C_CYAN='\033[36m'; C_OFF='\033[0m'
log()  { echo -e "${C_CYAN}[start-all]${C_OFF} $*"; }
ok()   { echo -e "${C_GREEN}  ✔${C_OFF} $*"; }
warn() { echo -e "${C_YELLOW}  !${C_OFF} $*"; }
err()  { echo -e "${C_RED}  ✘${C_OFF} $*"; }

# ----------------------------- 参数解析 -----------------------------
KILL_ONLY=0
START_FE=1
START_BE=1
for arg in "$@"; do
  case "${arg}" in
    --kill)   KILL_ONLY=1 ;;
    --no-fe)  START_FE=0  ;;
    --no-be)  START_BE=0  ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) warn "未知参数: ${arg}" ;;
  esac
done

# ----------------------------- 环境检测 -----------------------------
# Node / pnpm（非交互 shell 可能没有 nvm，手动兜底加载）
if ! command -v pnpm >/dev/null 2>&1; then
  if [ -s "${HOME}/.nvm/nvm.sh" ]; then
    export NVM_DIR="${HOME}/.nvm"
    # shellcheck disable=SC1091
    . "${NVM_DIR}/nvm.sh"
  fi
  for d in "${HOME}"/.nvm/versions/node/*/bin; do
    [ -d "${d}" ] && export PATH="${d}:${PATH}"
  done
fi

# Python 解释器：优先项目虚拟环境，其次系统 python3
if [ -x "${PY_VENV}/bin/python" ]; then
  PY="${PY_VENV}/bin/python"
else
  PY="$(command -v python3 || command -v python)"
fi

# ----------------------------- 停止逻辑 -----------------------------
kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -nP -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null)"
  if [ -n "${pids}" ]; then
    log "清理端口 ${port} 上的进程: ${pids}"
    echo "${pids}" | tr ' ' '\n' | xargs -r kill -9 2>/dev/null
  fi
}

kill_pattern() {
  local pattern="$1"
  local pids
  pids="$(pgrep -f "${pattern}" 2>/dev/null | grep -v "^$$\$" || true)"
  if [ -n "${pids}" ]; then
    log "清理进程 (${pattern}): $(echo "${pids}" | tr '\n' ' ')"
    echo "${pids}" | xargs -r kill -9 2>/dev/null
  fi
}

stop_all() {
  log "停止已有服务 ..."

  kill_port "${API_PORT}"
  kill_port "${FE_PORT}"

  kill_pattern "${BE_DIR}/run.py"
  kill_pattern "${BE_DIR}/worker.py"
  kill_pattern "src/worker/runner"
  kill_pattern "uvicorn src.api.main:app"
  kill_pattern "naive-ui-admin"
  kill_pattern "node_modules/.bin/vite"

  sleep 1
  ok "已有进程已清理"
}

stop_all

if [ "${KILL_ONLY}" -eq 1 ]; then
  log "已按 --kill 停止全部服务，不启动新进程。"
  exit 0
fi

# ----------------------------- 启动后端 -----------------------------
if [ "${START_BE}" -eq 1 ]; then
  log "启动后端 API  (${PY} run.py, :${API_PORT}) ..."
  cd "${BE_DIR}" || exit 1
  nohup "${PY}" run.py > "${LOG_DIR}/api.log" 2>&1 &
  echo $! > "${LOG_DIR}/api.pid"

  log "启动 Worker   (${PY} worker.py) ..."
  nohup "${PY}" worker.py > "${LOG_DIR}/worker.log" 2>&1 &
  echo $! > "${LOG_DIR}/worker.pid"
  ok "后端进程已拉起 (api.pid=$(cat "${LOG_DIR}/api.pid"), worker.pid=$(cat "${LOG_DIR}/worker.pid"))"
fi

# ----------------------------- 启动前端 -----------------------------
if [ "${START_FE}" -eq 1 ]; then
  # 直接调用项目内 vite，绕过 pnpm 的 deps 状态检查（pnpm 11 会在 dev 前自动
  # 触发 install，在本项目会因 ERR_PNPM_IGNORED_BUILDS 失败）
  VITE_BIN="${FE_DIR}/node_modules/.bin/vite"
  if [ ! -x "${VITE_BIN}" ]; then
    err "未找到 vite: ${VITE_BIN}，请先在 ${FE_DIR} 执行 pnpm install"
    exit 1
  fi
  log "启动前端 (vite, :${FE_PORT}) ..."
  cd "${FE_DIR}" || exit 1
  nohup "${VITE_BIN}" --host > "${LOG_DIR}/frontend.log" 2>&1 &
  echo $! > "${LOG_DIR}/frontend.pid"
  ok "前端进程已拉起 (frontend.pid=$(cat "${LOG_DIR}/frontend.pid"))"
fi

# ----------------------------- 健康检查 -----------------------------
wait_for() {
  local name="$1" url="$2" timeout="$3" i=0
  while [ "${i}" -lt "${timeout}" ]; do
    if curl -s -o /dev/null -w '%{http_code}' "${url}" 2>/dev/null | grep -qE '^(200|301|302|307|404)$'; then
      ok "${name} 就绪 -> ${url}"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  err "${name} ${timeout}s 内未就绪，请查看日志: ${LOG_DIR}"
  return 1
}

log "等待服务就绪 ..."
RC=0
[ "${START_BE}" -eq 1 ] && wait_for "后端 API" "http://127.0.0.1:${API_PORT}/docs" 40 || RC=1
[ "${START_FE}" -eq 1 ] && wait_for "前端"     "http://127.0.0.1:${FE_PORT}/"      60 || RC=1

echo ""
if [ "${RC}" -eq 0 ]; then
  ok "全部服务启动完成"
else
  warn "部分服务可能未就绪，请检查日志"
fi
echo -e "${C_GREEN}--------------------------------------------------------------${C_OFF}"
echo -e "  前端页面   : ${C_GREEN}http://localhost:${FE_PORT}/${C_OFF}"
echo -e "  后端 API   : ${C_GREEN}http://localhost:${API_PORT}/docs${C_OFF}"
echo -e "  API 日志   : ${LOG_DIR}/api.log"
echo -e "  Worker 日志: ${LOG_DIR}/worker.log"
echo -e "  前端日志   : ${LOG_DIR}/frontend.log"
echo -e "${C_GREEN}--------------------------------------------------------------${C_OFF}"
echo -e "  停止服务   : ${C_YELLOW}${BE_DIR}/scripts/start-all.sh --kill${C_OFF}"
echo ""

exit "${RC}"
