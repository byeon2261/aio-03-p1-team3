-- 0008_feedback_action.sql — feedback 필드 수정 행의 동작 구분 (I2 작업 A)
-- Supabase SQL 편집기에 그대로 붙여 실행한다. 여러 번 실행해도 안전하게 썼다.
-- 새 서버 코드를 배포하기 "전에" 실행한다(새 코드는 action 열에 값을 넣는다).
--
-- 규약
--   field_name 있는 행(필드 수정):
--     action = 'set'     corrected_value가 사용자 값. null이면 "메모에 없음(미기재)"으로 고친 것
--     action = 'revert'  수정 취소(AI 값으로 되돌림). corrected_value는 null
--   field_name 없는 행(전체 평가): action은 null
-- 필드별 최신 행이 유효하다(feedback은 새 행 추가 방식).
-- 권한: 0003의 테이블 단위 grant(select, insert, delete)가 새 열에도 적용된다. RLS 정책은 그대로다.

alter table public.feedback add column if not exists action text;

-- 기존 행 채우기: 0008 이전에는 corrected_value null이 "수정 취소"였다.
update public.feedback
   set action = case
                    when corrected_value is null or corrected_value = 'null'::jsonb then 'revert'
                    else 'set'
                end
 where field_name is not null
   and action is null;

alter table public.feedback drop constraint if exists feedback_action_check;
alter table public.feedback add constraint feedback_action_check check (
    (field_name is null and action is null)
    or (field_name is not null and action = 'set')
    or (field_name is not null and action = 'revert'
        and (corrected_value is null or corrected_value = 'null'::jsonb))
);

comment on column public.feedback.action is
    '필드 수정 행의 동작: set(값으로 고침, null이면 메모에 없음) | revert(AI 값으로 되돌림). 전체 평가 행은 null';
