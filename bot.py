import os
import sqlite3
import time
import secrets
import random
import asyncio
import discord
from discord.ext import commands

# Подключаем библиотеку для чтения .env файла
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️ ВНИМАНИЕ: Библиотека python-dotenv не установлена.")
    print("Выполни в консоли: pip install python-dotenv")

# ============================================================
#  НАСТРОЙКИ
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'keys.db')

# Токен берется из файла .env (переменная DISCORD_TOKEN)
BOT_TOKEN = os.environ.get("DISCORD_TOKEN")

if not BOT_TOKEN:
    print("❌ ОШИБКА: Токен не найден!")
    print("Создай файл .env в папке с ботом и напиши там: DISCORD_TOKEN=твой_токен")
    exit(1)

# ID ролей
ADMIN_ROLE_ID = 1390996907115024464
USER_ROLE_ID = 1390996808108478536

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ============================================================
#  БД
# ============================================================
def db_query(query, params=(), commit=False, fetchall=False, fetchone=False):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(query, params)
    result = None
    if fetchall:
        result = cur.fetchall()
    elif fetchone:
        result = cur.fetchone()
    if commit:
        conn.commit()
    conn.close()
    return result

def generate_key():
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    part = lambda: ''.join(secrets.choice(chars) for _ in range(4))
    return f'ANA-{part()}-{part()}-{part()}-{part()}'

def _now_ms():
    return int(time.time() * 1000)

# ============================================================
#  ПРОВЕРКИ РОЛЕЙ
# ============================================================
def is_admin():
    async def predicate(ctx):
        if discord.utils.get(ctx.author.roles, id=ADMIN_ROLE_ID):
            return True
        await ctx.send("❌ Нужна роль **Администратора**.")
        return False
    return commands.check(predicate)

def is_user():
    async def predicate(ctx):
        if (discord.utils.get(ctx.author.roles, id=USER_ROLE_ID) or
                discord.utils.get(ctx.author.roles, id=ADMIN_ROLE_ID)):
            return True
        await ctx.send("❌ Нужна роль **Пользователя** (подписка).")
        return False
    return commands.check(predicate)

# ============================================================
#  ON_READY
# ============================================================
@bot.event
async def on_ready():
    print(f'🔥 Бот {bot.user.name} запущен!')
    print(f'📂 База данных: {DB_PATH}')
    try:
        synced = await bot.tree.sync()
        print(f'✅ Синхронизировано {len(synced)} слэш-команд')
    except Exception as e:
        print(f'⚠️ Ошибка синхронизации слэш-команд: {e}')

# ============================================================
#  АДМИН-КОМАНДЫ
# ============================================================

@bot.command(name="создать")
@is_admin()
async def create_sub(ctx, amount: int, unit: str):
    """Создать ключ. Пример: !создать 30 days"""
    unit = unit.lower()
    if unit not in ('minutes', 'hours', 'days'):
        await ctx.send("❌ Единицы: `minutes`, `hours`, `days`.")
        return
    mult = {'minutes': 60_000, 'hours': 3_600_000, 'days': 86_400_000}[unit]
    exp = _now_ms() + amount * mult
    key = generate_key()
    db_query('INSERT INTO keys (key, expires_at) VALUES (?, ?)', (key, exp), commit=True)
    await ctx.send(f"🔑 **Ключ создан:**\n`{key}`\nДлительность: **{amount} {unit}**")

@bot.command(name="бан_ключ")
@is_admin()
async def ban_key(ctx, key: str):
    """Забанить ключ."""
    key = key.strip().upper()
    if not db_query('SELECT 1 FROM keys WHERE key = ?', (key,), fetchone=True):
        await ctx.send("❌ Ключ не найден.")
        return
    db_query('UPDATE keys SET banned = 1 WHERE key = ?', (key,), commit=True)
    await ctx.send(f"⛔ Ключ `{key}` забанен.")

@bot.command(name="разбан_ключ")
@is_admin()
async def unban_key(ctx, key: str):
    """Разбанить ключ."""
    key = key.strip().upper()
    db_query('UPDATE keys SET banned = 0 WHERE key = ?', (key,), commit=True)
    await ctx.send(f"✅ Ключ `{key}` разбанен.")

@bot.command(name="сброс_хвид")
@is_admin()
async def reset_hwid(ctx, key: str):
    """Сбросить HWID."""
    key = key.strip().upper()
    db_query('UPDATE keys SET hwid = NULL, suspicious_count = 0 WHERE key = ?', (key,), commit=True)
    await ctx.send(f"🔄 HWID для `{key}` сброшен.")

@bot.command(name="заморозить")
@is_admin()
async def freeze_key(ctx, key: str):
    """Заморозить подписку (сохраняет остаток времени)."""
    key = key.strip().upper()
    row = db_query('SELECT * FROM keys WHERE key = ?', (key,), fetchone=True)
    if not row:
        await ctx.send("❌ Ключ не найден.")
        return
    if row['frozen']:
        await ctx.send("❄️ Ключ уже заморожен.")
        return
    left = max(0, row['expires_at'] - _now_ms())
    db_query('UPDATE keys SET frozen = 1, frozen_time_left = ? WHERE key = ?', (left, key), commit=True)
    await ctx.send(f"❄️ Ключ `{key}` заморожен. Остаток: {left // 60000} мин.")

@bot.command(name="разморозить")
@is_admin()
async def unfreeze_key(ctx, key: str):
    """Разморозить подписку."""
    key = key.strip().upper()
    row = db_query('SELECT * FROM keys WHERE key = ?', (key,), fetchone=True)
    if not row or not row['frozen']:
        await ctx.send("❌ Ключ не найден или не заморожен.")
        return
    new_exp = _now_ms() + row['frozen_time_left']
    db_query('UPDATE keys SET frozen = 0, frozen_time_left = 0, expires_at = ? WHERE key = ?',
             (new_exp, key), commit=True)
    await ctx.send(f"✅ Ключ `{key}` разморожен.")

@bot.command(name="бан_ип")
@is_admin()
async def ban_ip(ctx, ip: str, *, reason: str = "без причины"):
    """Забанить IP. Пример: !бан_ип 1.2.3.4 Читер"""
    db_query('INSERT OR REPLACE INTO ip_bans (ip, reason) VALUES (?, ?)', (ip, reason), commit=True)
    await ctx.send(f"⛔ IP `{ip}` забанен. Причина: {reason}")

@bot.command(name="разбан_ип")
@is_admin()
async def unban_ip(ctx, ip: str):
    """Разбанить IP."""
    db_query('DELETE FROM ip_bans WHERE ip = ?', (ip,), commit=True)
    await ctx.send(f"✅ IP `{ip}` разбанен.")

@bot.command(name="техработы")
@is_admin()
async def toggle_maintenance(ctx):
    """Включить/выключить техработы на сервере."""
    row = db_query("SELECT value FROM settings WHERE key = 'maintenance'", fetchone=True)
    cur = row['value'] if row else '0'
    new = '0' if cur == '1' else '1'
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES ('maintenance', ?)", (new,), commit=True)
    await ctx.send(f"🛠 Техработы: **{'ВКЛ' if new == '1' else 'ВЫКЛ'}**")

@bot.command(name="логи")
@is_admin()
async def show_logs(ctx, limit: int = 15):
    """Показать последние действия."""
    rows = db_query('SELECT * FROM logs ORDER BY id DESC LIMIT ?', (limit,), fetchall=True)
    if not rows:
        await ctx.send("Логов нет.")
        return
    embed = discord.Embed(title="Последние действия", color=discord.Color.orange())
    for r in rows:
        t = time.strftime('%m-%d %H:%M', time.localtime(r['timestamp'] / 1000))
        embed.add_field(
            name=f"{t} — {r['key'] or 'N/A'}",
            value=f"IP: `{r['ip'] or '—'}`\n{r['action']}",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name="ключи")
@is_admin()
async def list_keys(ctx, page: int = 1):
    """Список всех ключей (по 10 на страницу)."""
    per = 10
    rows = db_query('SELECT * FROM keys ORDER BY id DESC LIMIT ? OFFSET ?',
                    (per, (page - 1) * per), fetchall=True)
    total = db_query('SELECT COUNT(*) AS c FROM keys', fetchone=True)['c']
    if not rows:
        await ctx.send("Ключей нет.")
        return
    embed = discord.Embed(title=f"Ключи (стр. {page}, всего {total})", color=discord.Color.blue())
    for r in rows:
        status = "⛔ Бан" if r['banned'] else ("❄️ Заморожен" if r['frozen'] else
                 ("✅ Активен" if r['expires_at'] > _now_ms() else "⌛ Истёк"))
        exp = time.strftime('%Y-%m-%d %H:%M', time.localtime(r['expires_at'] / 1000))
        embed.add_field(
            name=f"`{r['key']}`",
            value=f"{status} | до {exp}\nHWID: `{r['hwid'][:16] if r['hwid'] else '—'}`",
            inline=False
        )
    await ctx.send(embed=embed)

# ============================================================
#  ПОЛЬЗОВАТЕЛЬСКИЕ КОМАНДЫ
# ============================================================

@bot.command(name="инфо")
@is_user()
async def check_key(ctx, key: str):
    """Инфо о ключе."""
    key = key.strip().upper()
    row = db_query('SELECT * FROM keys WHERE key = ?', (key,), fetchone=True)
    if not row:
        await ctx.send("❌ Ключ не найден.")
        return
    exp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row['expires_at'] / 1000))
    status = "Бан ⛔" if row['banned'] else ("Заморожен ❄️" if row['frozen'] else "Активен ✅")
    embed = discord.Embed(title="Информация о ключе", color=discord.Color.blue())
    embed.add_field(name="Ключ", value=f"`{row['key']}`", inline=False)
    embed.add_field(name="Статус", value=status)
    embed.add_field(name="Истекает", value=exp)
    embed.add_field(name="HWID", value="Есть 📱" if row['hwid'] else "Отсутствует ❌")
    await ctx.send(embed=embed)

# ============================================================
#  ИГРА «САПЁР» (Награда: роль пользователя)
# ============================================================

class MinesweeperView(discord.ui.View):
    def __init__(self, bombs: int, author: discord.Member, grid_size: int = 5):
        super().__init__(timeout=300)
        self.grid_size = grid_size
        self.bombs = bombs
        self.author = author
        self.revealed = [[False] * grid_size for _ in range(grid_size)]
        self.grid = [["0"] * grid_size for _ in range(grid_size)]
        self.game_over = False
        self._build_grid()
        self._build_buttons()

    def _build_grid(self):
        placed = 0
        while placed < self.bombs:
            r = random.randint(0, self.grid_size - 1)
            c = random.randint(0, self.grid_size - 1)
            if self.grid[r][c] != "💣":
                self.grid[r][c] = "💣"
                placed += 1
        for r in range(self.grid_size):
            for c in range(self.grid_size):
                if self.grid[r][c] == "💣":
                    continue
                cnt = 0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < self.grid_size and 0 <= nc < self.grid_size \
                                and self.grid[nr][nc] == "💣":
                            cnt += 1
                self.grid[r][c] = str(cnt)

    def _build_buttons(self):
        emoji_map = {"0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣",
                     "4": "4️⃣", "5": "5️⃣", "6": "6️⃣", "7": "7️⃣",
                     "8": "8️⃣", "💣": "💣"}
        for r in range(self.grid_size):
            for c in range(self.grid_size):
                btn = discord.ui.Button(
                    label="?",
                    style=discord.ButtonStyle.secondary,
                    row=r,
                    custom_id=f"cell_{r}_{c}"
                )
                btn.callback = self._make_callback(r, c)
                self.add_item(btn)
        self.emoji_map = emoji_map

    def _make_callback(self, r, c):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.author.id:
                await interaction.response.send_message("Это не твоя игра!", ephemeral=True)
                return
            if self.game_over:
                await interaction.response.send_message("Игра окончена.", ephemeral=True)
                return
            if self.revealed[r][c]:
                await interaction.response.send_message("Уже открыто.", ephemeral=True)
                return

            self.revealed[r][c] = True
            cell = self.grid[r][c]

            btn = None
            for it in self.children:
                if it.custom_id == f"cell_{r}_{c}":
                    btn = it
                    break

            if cell == "💣":
                self.game_over = True
                for rr in range(self.grid_size):
                    for cc in range(self.grid_size):
                        for it in self.children:
                            if it.custom_id == f"cell_{rr}_{cc}":
                                val = self.grid[rr][cc]
                                it.label = self.emoji_map[val]
                                if val == "💣":
                                    it.style = discord.ButtonStyle.danger
                                else:
                                    it.style = discord.ButtonStyle.secondary
                                it.disabled = True
                await interaction.response.edit_message(
                    content="💥 **Ты наступил на мину! Игра окончена.**",
                    view=self
                )
                self.stop()
                return

            btn.label = self.emoji_map[cell]
            btn.style = discord.ButtonStyle.success
            btn.disabled = True

            opened = sum(sum(1 for x in row if x) for row in self.revealed)
            total_safe = self.grid_size * self.grid_size - self.bombs
            if opened >= total_safe:
                self.game_over = True
                for it in self.children:
                    it.disabled = True
                
                role = interaction.guild.get_role(USER_ROLE_ID)
                reward_text = ""
                if role:
                    try:
                        await interaction.user.add_roles(role, reason="Победа в Сапёре")
                        reward_text = f"\n🎁 Тебе выдана роль {role.mention}!"
                    except discord.Forbidden:
                        reward_text = "\n⚠️ Не смог выдать роль (проверь права бота)."
                
                await interaction.response.edit_message(
                    content=f"🎉 **Победа! Все безопасные клетки открыты.**{reward_text}",
                    view=self
                )
                self.stop()
                return

            await interaction.response.edit_message(view=self)
        return cb

@bot.command(name="сапер")
async def minesweeper(ctx, bombs: int = 5):
    """Кнопочный сапёр. Победа = выдача роли пользователя."""
    if bombs < 1 or bombs > 15:
        await ctx.send("❌ Кол-во бомб: 1–15.")
        return
    view = MinesweeperView(bombs=bombs, author=ctx.author)
    role = discord.utils.get(ctx.guild.roles, id=USER_ROLE_ID)
    role_mention = role.mention if role else "пользователя"
    
    embed = discord.Embed(
        title="💥 Сапёр",
        description=f"Поле 5×5, мин: **{bombs}**.\nПобеда = выдача роли {role_mention}",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)

@bot.command(name="куб")
async def roll_dice(ctx):
    """Бросить кубик."""
    await ctx.send(f"🎲 Выпало: **{random.randint(1, 6)}**")

# ============================================================
#  ЗАПУСК
# ============================================================
if __name__ == "__main__":
    bot.run(BOT_TOKEN)=============
#  ИГРА «САПЁР» с выдачей роли за победу
# ============================================================

class MinesweeperView(discord.ui.View):
    """Кнопочный сапёр с спойлерами невозможно, поэтому используем кнопки-клетки."""
    def __init__(self, bombs: int, author: discord.Member, grid_size: int = 5):
        super().__init__(timeout=300)
        self.grid_size = grid_size
        self.bombs = bombs
        self.author = author
        self.revealed = [[False] * grid_size for _ in range(grid_size)]
        self.grid = [["0"] * grid_size for _ in range(grid_size)]
        self.game_over = False
        self._build_grid()
        self._build_buttons()

    def _build_grid(self):
        placed = 0
        while placed < self.bombs:
            r = random.randint(0, self.grid_size - 1)
            c = random.randint(0, self.grid_size - 1)
            if self.grid[r][c] != "💣":
                self.grid[r][c] = "💣"
                placed += 1
        for r in range(self.grid_size):
            for c in range(self.grid_size):
                if self.grid[r][c] == "💣":
                    continue
                cnt = 0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < self.grid_size and 0 <= nc < self.grid_size \
                                and self.grid[nr][nc] == "💣":
                            cnt += 1
                self.grid[r][c] = str(cnt)

    def _build_buttons(self):
        emoji_map = {"0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣",
                     "4": "4️⃣", "5": "5️⃣", "6": "6️⃣", "7": "7️⃣",
                     "8": "8️⃣", "💣": "💣"}
        for r in range(self.grid_size):
            for c in range(self.grid_size):
                btn = discord.ui.Button(
                    label="?",
                    style=discord.ButtonStyle.secondary,
                    row=r,
                    custom_id=f"cell_{r}_{c}"
                )
                btn.callback = self._make_callback(r, c)
                self.add_item(btn)
        self.emoji_map = emoji_map

    def _make_callback(self, r, c):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.author.id:
                await interaction.response.send_message("Это не твоя игра!", ephemeral=True)
                return
            if self.game_over:
                await interaction.response.send_message("Игра окончена.", ephemeral=True)
                return
            if self.revealed[r][c]:
                await interaction.response.send_message("Уже открыто.", ephemeral=True)
                return

            self.revealed[r][c] = True
            cell = self.grid[r][c]

            # Найти кнопку
            btn = None
            for it in self.children:
                if it.custom_id == f"cell_{r}_{c}":
                    btn = it
                    break

            if cell == "💣":
                # Проигрыш — открываем всё
                self.game_over = True
                for rr in range(self.grid_size):
                    for cc in range(self.grid_size):
                        for it in self.children:
                            if it.custom_id == f"cell_{rr}_{cc}":
                                val = self.grid[rr][cc]
                                it.label = self.emoji_map[val]
                                if val == "💣":
                                    it.style = discord.ButtonStyle.danger
                                else:
                                    it.style = discord.ButtonStyle.secondary
                                it.disabled = True
                await interaction.response.edit_message(
                    content="💥 **Ты наступил на мину! Игра окончена.**",
                    view=self
                )
                self.stop()
                return

            btn.label = self.emoji_map[cell]
            btn.style = discord.ButtonStyle.success
            btn.disabled = True

            # Проверка победы
            opened = sum(sum(1 for x in row if x) for row in self.revealed)
            total_safe = self.grid_size * self.grid_size - self.bombs
            if opened >= total_safe:
                self.game_over = True
                for it in self.children:
                    it.disabled = True
                # Выдаём роль пользователю
                role = interaction.guild.get_role(USER_ROLE_ID)
                reward_text = ""
                if role:
                    try:
                        await interaction.user.add_roles(role, reason="Победа в Сапёре")
                        reward_text = f"\n🎁 Тебе выдана роль {role.mention}!"
                    except discord.Forbidden:
                        reward_text = "\n⚠️ Не смог выдать роль (проверь права бота)."
                await interaction.response.edit_message(
                    content=f"🎉 **Победа! Все безопасные клетки открыты.**{reward_text}",
                    view=self
                )
                self.stop()
                return

            await interaction.response.edit_message(view=self)
        return cb


@bot.command(name="сапер")
async def minesweeper(ctx, bombs: int = 5):
    """Кнопочный сапёр. Победа = выдача роли пользователя."""
    if bombs < 1 or bombs > 15:
        await ctx.send("❌ Кол-во бомб: 1–15.")
        return
    view = MinesweeperView(bombs=bombs, author=ctx.author)
    embed = discord.Embed(
        title="💥 Сапёр",
        description=f"Поле 5×5, мин: **{bombs}**.\nПобеда = выдача роли {discord.utils.get(ctx.guild.roles, id=USER_ROLE_ID).mention if discord.utils.get(ctx.guild.roles, id=USER_ROLE_ID) else 'пользователя'}",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)

@bot.command(name="куб")
async def roll_dice(ctx):
    """Бросить кубик."""
    await ctx.send(f"🎲 Выпало: **{random.randint(1, 6)}**")

# ============================================================
#  ЗАПУСК
# ============================================================
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
