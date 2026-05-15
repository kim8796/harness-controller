# Harness Task Intake

요구사항을 draft로 만들고, 검토한 뒤 실행 가능한 backlog로 넣는 방법이다.

## 기본 흐름

```bash
./harness task
./harness task list
./harness task review <packet-id>
./harness task queue <packet-id> --auto
./harness run
```

`task draft`와 `task from`도 쓸 수 있지만, 처음에는 bare `./harness task` 인터뷰를 권장한다.

## Draft 작성

인터뷰로 만든다.

```bash
./harness task
```

파일에서 가져온다.

```bash
./harness task from /path/to/request.md
```

이미지 참고를 붙인다.

```bash
./harness task from /path/to/request.md --image /path/to/screenshot.png
```

이미지는 base64로 backlog에 넣지 않는다. controller sidecar에 path, media type, size, sha256, caption만 기록한다.

## 외부 에디터로 수정

출력된 `targets/<id>/backlog/drafts/<packet-id>/request.md`는 외부 에디터로 수정해도 된다. 수정 후에는 다시 review한다.

```bash
./harness task review <packet-id>
```

`request.md`가 review 뒤 바뀌면 `task list`에서 `다시 검토 필요`로 표시된다.

## AI advisory review

```bash
./harness task review <packet-id> --ai
```

이 명령은 모델을 직접 실행하지 않는다. packet-local prompt/schema와 선택적 advisory response artifact만 만든다. deterministic `review.json`을 바꾸지 않고 `queue --auto` 판단에도 사용하지 않는다.

## Queue

manual-review로 queue:

```bash
./harness task queue <packet-id>
```

auto 실행 후보로 queue:

```bash
./harness task queue <packet-id> --auto
```

`--auto`는 아래가 명확해야 통과한다.

- 목표와 acceptance
- 허용 file scope
- 금지 scope 위반 없음
- deterministic validation command
- secret이나 credential 직접 입력 없음

모호한 요구사항, 이미지 단독 요구사항, credential/manual smoke가 필요한 작업은 `manual-review`로 남기는 것이 정상이다.

## 실행 단위

draft는 source of truth가 아니다. 실제 실행 단위는 `task queue`가 만든 canonical sidecar backlog markdown이다.

실행 후 결과를 닫을 때는 [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md)의 `finish` 흐름을 따른다.
