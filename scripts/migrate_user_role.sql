-- P6: users 表增加角色列，支持 user/admin 分离
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user';

-- admin 角色可管理所有领域，user 只能查看
CREATE INDEX IF NOT EXISTS idx_users_role ON public.users(role);

-- 如有需要，将第一个用户提升为管理员（手动执行）
-- UPDATE public.users SET role = 'admin' WHERE id = 1;
