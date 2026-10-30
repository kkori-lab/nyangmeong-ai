#!/bin/sh
# /end에서 사람이 PR이라고 답한 뒤의 기계적인 단계: 원격 develop 합치기, 검증 명령, 푸시.
# PR 제목·본문과 gh pr create는 /end가 한다. 병합은 사람이 GitHub에서 한다.
# merge로 합치고 rebase하지 않는다. 충돌이 나면 merge --abort 하지 않고 그대로 멈춘다(docs/convention/git.md).
# 커밋하지 않은 변경이 있으면 종료 코드 4로 멈춘다. 사람에게 물은 뒤 --allow-dirty로 다시 돌리면 그대로 두고 진행한다.
# 사용: sh scripts/pr-prep.sh [--allow-dirty]
cd "$(git rev-parse --show-toplevel)" || exit 1
branch=$(git branch --show-current)
case "$branch" in
  develop | main | "") echo "자기 이니셜 브랜치에서만 씁니다(지금: ${branch:-브랜치 없음})"; exit 1 ;;
esac
if [ -n "$(git status --porcelain)" ]; then
  if [ "$1" != "--allow-dirty" ]; then
    echo "커밋하지 않은 변경이 있습니다. 그대로 두고 진행할지 사람에게 묻고, 진행하면 --allow-dirty로 다시 돌리세요:"
    git status -s
    exit 4
  fi
  echo "커밋하지 않은 변경을 그대로 두고 진행합니다(푸시에는 들어가지 않고, 검증 명령에는 포함됩니다)"
fi

git fetch -q origin || { echo "fetch 실패"; exit 1; }
n=$(git rev-list --count HEAD..origin/develop)
if [ "$n" != 0 ]; then
  echo "origin/develop에서 커밋 ${n}개를 합칩니다"
  if ! git merge -q --no-edit origin/develop; then
    echo "충돌이 났습니다. merge --abort 하지 않고 그대로 둡니다. 충돌 파일:"
    git diff --name-only --diff-filter=U | sed 's/^/- /'
    exit 1
  fi
fi

# 검증 명령은 scripts/check.sh 하나다(AGENTS.md)
sh scripts/check.sh
code=$?
echo "sh scripts/check.sh → $code"
[ "$code" = 0 ] || exit 1

git push -q origin "$branch" || { echo "푸시 실패"; exit 1; }
echo "푸시함: origin/$branch"
git log --oneline origin/develop..HEAD
