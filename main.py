import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import json
import hashlib
import secrets
import re
from datetime import datetime

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discord.log', encoding='utf-8', mode='a'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('discord_bot')

# Bot intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True


# Configuration - CHANGE THESE VALUES AFTER RUNNING !get_roles
CUSTOMER_ROLE_ID = 123456789012345678  # Replace with your actual Customer role ID
VERIFIED_ROLE_ID = 987654321098765432  # Replace with your Verified role ID (users who generated keys)
ADMIN_ROLE_ID = 1470689456444018761  # Replace with your Admin role ID


# ==================== DATABASE CLASS ====================

class Database:
    """Simple JSON-based database for user accounts and keys"""

    def __init__(self, accounts_file='accounts.json', keys_file='keys.json'):
        self.accounts_file = accounts_file
        self.keys_file = keys_file
        self.accounts = self._load_file(accounts_file)
        self.keys = self._load_file(keys_file)

    def _load_file(self, filename):
        """Load JSON file or create empty dict"""
        try:
            with open(filename, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _save_accounts(self):
        """Save accounts to file"""
        with open(self.accounts_file, 'w') as f:
            json.dump(self.accounts, f, indent=4)

    def _save_keys(self):
        """Save keys to file"""
        with open(self.keys_file, 'w') as f:
            json.dump(self.keys, f, indent=4)

    def hash_password(self, password):
        """Hash password with SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()

    def create_account(self, discord_id, email, password):
        """Create new user account"""
        discord_id = str(discord_id)

        if discord_id in self.accounts:
            return False, "Account already exists"

        for acc in self.accounts.values():
            if acc['email'].lower() == email.lower():
                return False, "Email already registered"

        self.accounts[discord_id] = {
            'email': email,
            'password': self.hash_password(password),
            'created_at': datetime.utcnow().isoformat(),
            'verified': False,
            'key': None,
            'key_generated': False
        }
        self._save_accounts()
        return True, "Account created successfully"

    def verify_login(self, discord_id, password):
        """Verify login credentials"""
        discord_id = str(discord_id)

        if discord_id not in self.accounts:
            return False

        return self.accounts[discord_id]['password'] == self.hash_password(password)

    def reset_password(self, discord_id, old_password, new_password):
        """Reset user password"""
        discord_id = str(discord_id)

        if discord_id not in self.accounts:
            return False, "Account not found"

        if not self.verify_login(discord_id, old_password):
            return False, "Incorrect current password"

        self.accounts[discord_id]['password'] = self.hash_password(new_password)
        self._save_accounts()
        return True, "Password reset successfully"

    def get_account(self, discord_id):
        """Get account info"""
        return self.accounts.get(str(discord_id))

    def generate_key_for_user(self, discord_id, product_name="Premium"):
        """Generate a unique product key for logged-in user"""
        discord_id = str(discord_id)

        if discord_id not in self.accounts:
            return False, None, "No account found"

        if self.accounts[discord_id]['key_generated']:
            return False, None, "You have already generated a key. Contact admin for a new one."

        # Generate unique key
        key = f"{product_name.upper()[:4]}-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"

        self.keys[key] = {
            'product': product_name,
            'duration_days': 30,
            'created_at': datetime.utcnow().isoformat(),
            'generated_by': discord_id,
            'redeemed': True,  # Auto-redeemed by generator
            'redeemed_by': discord_id,
            'redeemed_at': datetime.utcnow().isoformat()
        }

        # Update account
        self.accounts[discord_id]['verified'] = True
        self.accounts[discord_id]['key'] = key
        self.accounts[discord_id]['key_generated'] = True

        self._save_keys()
        self._save_accounts()

        return True, key, "Key generated successfully"

    def admin_generate_key(self, product_name, duration_days=30):
        """Admin-only key generation (not auto-redeemed)"""
        key = f"{product_name.upper()[:4]}-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"

        self.keys[key] = {
            'product': product_name,
            'duration_days': duration_days,
            'created_at': datetime.utcnow().isoformat(),
            'generated_by': 'admin',
            'redeemed': False,
            'redeemed_by': None,
            'redeemed_at': None
        }
        self._save_keys()
        return key

    def redeem_key(self, discord_id, key):
        """Redeem a product key"""
        discord_id = str(discord_id)

        if key not in self.keys:
            return False, "Invalid key"

        if self.keys[key]['redeemed']:
            return False, "Key already redeemed"

        if discord_id not in self.accounts:
            return False, "No account found. Please register first"

        self.keys[key]['redeemed'] = True
        self.keys[key]['redeemed_by'] = discord_id
        self.keys[key]['redeemed_at'] = datetime.utcnow().isoformat()

        self.accounts[discord_id]['verified'] = True
        self.accounts[discord_id]['key'] = key

        self._save_keys()
        self._save_accounts()

        return True, f"Key redeemed successfully! Product: {self.keys[key]['product']}"


# Initialize database
db = Database()


# ==================== MODALS ====================

class RegisterModal(discord.ui.Modal, title="Create Account"):
    """Modal for user registration"""

    email = discord.ui.TextInput(
        label="Email",
        placeholder="your.email@example.com",
        required=True,
        max_length=100
    )

    password = discord.ui.TextInput(
        label="Password",
        placeholder="Enter a secure password",
        required=True,
        min_length=6,
        max_length=50,
        style=discord.TextStyle.short
    )

    confirm_password = discord.ui.TextInput(
        label="Confirm Password",
        placeholder="Re-enter your password",
        required=True,
        min_length=6,
        max_length=50,
        style=discord.TextStyle.short
    )

    async def on_submit(self, interaction: discord.Interaction):
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, str(self.email)):
            await interaction.response.send_message("❌ Invalid email format!", ephemeral=True)
            return

        if str(self.password) != str(self.confirm_password):
            await interaction.response.send_message("❌ Passwords do not match!", ephemeral=True)
            return

        success, message = db.create_account(interaction.user.id, str(self.email), str(self.password))

        if success:
            embed = discord.Embed(
                title="✅ Account Created!",
                description="Your account has been created successfully.",
                color=0x2ECC71
            )
            embed.add_field(name="Email", value=str(self.email), inline=False)
            embed.add_field(
                name="Next Steps",
                value="1. Login using the **Login** button\n2. Use `!generate_key` command to get your product key\n3. You'll receive a special verified role!",
                inline=False
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"Account created for {interaction.user} ({interaction.user.id})")
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)


class LoginModal(discord.ui.Modal, title="Login to Account"):
    """Modal for user login"""

    password = discord.ui.TextInput(
        label="Password",
        placeholder="Enter your password",
        required=True,
        style=discord.TextStyle.short
    )

    async def on_submit(self, interaction: discord.Interaction):
        if db.verify_login(interaction.user.id, str(self.password)):
            account = db.get_account(interaction.user.id)

            embed = discord.Embed(title="✅ Login Successful", color=0x2ECC71)
            embed.add_field(name="Email", value=account['email'], inline=False)
            embed.add_field(name="Key Generated", value="✅ Yes" if account['key_generated'] else "❌ No", inline=True)
            embed.add_field(name="Active Key", value=account['key'] if account['key'] else "None", inline=True)

            if not account['key_generated']:
                embed.add_field(
                    name="Generate Your Key",
                    value="Type `!generate_key` to get your product key!",
                    inline=False
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Incorrect password!", ephemeral=True)


class ResetPasswordModal(discord.ui.Modal, title="Reset Password"):
    """Modal for password reset"""

    current_password = discord.ui.TextInput(
        label="Current Password",
        placeholder="Enter your current password",
        required=True,
        style=discord.TextStyle.short
    )

    new_password = discord.ui.TextInput(
        label="New Password",
        placeholder="Enter new password",
        required=True,
        min_length=6,
        style=discord.TextStyle.short
    )

    confirm_password = discord.ui.TextInput(
        label="Confirm New Password",
        placeholder="Re-enter new password",
        required=True,
        min_length=6,
        style=discord.TextStyle.short
    )

    async def on_submit(self, interaction: discord.Interaction):
        if str(self.new_password) != str(self.confirm_password):
            await interaction.response.send_message("❌ New passwords do not match!", ephemeral=True)
            return

        success, message = db.reset_password(
            interaction.user.id,
            str(self.current_password),
            str(self.new_password)
        )

        if success:
            await interaction.response.send_message("✅ Password reset successfully!", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)


class RedeemKeyModal(discord.ui.Modal, title="Redeem Product Key"):
    """Modal for key redemption"""

    key = discord.ui.TextInput(
        label="Product Key",
        placeholder="XXXX-XXXXXXXX-XXXXXXXX",
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        success, message = db.redeem_key(interaction.user.id, str(self.key).strip().upper())

        if success:
            role = interaction.guild.get_role(CUSTOMER_ROLE_ID)

            if role and role not in interaction.user.roles:
                try:
                    await interaction.user.add_roles(role, reason="Key redeemed")
                    await interaction.response.send_message(
                        f"✅ {message}\n🎉 You've been given the **{role.name}** role!",
                        ephemeral=True
                    )
                except discord.Forbidden:
                    await interaction.response.send_message(
                        f"✅ {message}\n⚠️ Could not assign role. Contact admin.",
                        ephemeral=True
                    )
            else:
                await interaction.response.send_message(f"✅ {message}", ephemeral=True)

            logger.info(f"Key redeemed by {interaction.user} ({interaction.user.id})")
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)


# ==================== BUTTON VIEWS ====================

class AccountView(discord.ui.View):
    """Persistent view for account management"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Register", style=discord.ButtonStyle.green, custom_id="register_button", emoji="📝")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterModal())

    @discord.ui.button(label="Login", style=discord.ButtonStyle.blurple, custom_id="login_button", emoji="🔐")
    async def login_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        account = db.get_account(interaction.user.id)
        if not account:
            await interaction.response.send_message("❌ No account found. Please register first!", ephemeral=True)
            return
        await interaction.response.send_modal(LoginModal())

    @discord.ui.button(label="Reset Password", style=discord.ButtonStyle.gray, custom_id="reset_password_button",
                       emoji="🔑")
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        account = db.get_account(interaction.user.id)
        if not account:
            await interaction.response.send_message("❌ No account found. Please register first!", ephemeral=True)
            return
        await interaction.response.send_modal(ResetPasswordModal())


class VerificationView(discord.ui.View):
    """Persistent view for key redemption"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Redeem Admin Key", style=discord.ButtonStyle.green, custom_id="redeem_key_button",
                       emoji="🎟️")
    async def redeem_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        account = db.get_account(interaction.user.id)
        if not account:
            await interaction.response.send_message(
                "❌ No account found. Please register first using the Account Management panel!",
                ephemeral=True
            )
            return
        await interaction.response.send_modal(RedeemKeyModal())


# ==================== BOT SETUP ====================

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)


@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord"""
    bot.add_view(AccountView())
    bot.add_view(VerificationView())

    logger.info(f"Bot logged in as {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")

    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="for new registrations")
    )


@bot.event
async def on_command_error(ctx, error):
    """Global error handler"""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: `{error.param.name}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument provided.")
    else:
        logger.error(f"Command error: {error}", exc_info=error)

#BOT EVENT -  WORD FILTER

@bot.event
async def on_message(message):
    if message.author == bot.user:  # FIX: removed stray dot after .author
        return

    # Words/phrases that trigger the "not an HvH cheat" response
    CHEAT_COMPLAINTS = [
        "this cheat is shit",
        "this cheats are shit",
        "cheat is trash",
        "cheats are trash",
        "cheat sucks",
        "cheats suck",
        "cheat is bad",
        "cheats are bad",
        "cheat is garbage",
        "cheats are garbage",
        "cheat is terrible",
        "worst cheat",
        "cheat doesn't work",
        "cheat dont work",
        "cheat is useless",
        "this cheat is horrible",
        "hvh cheat",
        "for hvh",
        "blatant cheat",
    ]

    content_lower = message.content.lower()

    if any(phrase in content_lower for phrase in CHEAT_COMPLAINTS):
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        await message.channel.send(  # FIX: was message.chanle (typo)
            f"{message.author.mention} ⚠️ This is **not** an HvH or blatant cheat — it is a **semi-legit** cheat. "
            f"Please read the product description before complaining!"
        )
        logger.info(f"Filtered cheat complaint from {message.author} ({message.author.id}): {message.content}")
        return

    await bot.process_commands(message)  # IMPORTANT: keeps all !commands working


# ==================== USER COMMANDS ====================

@bot.command(name='generate_key')
async def user_generate_key(ctx):
    """
    Generate your own product key (must be logged in first)
    Usage: !generate_key
    """
    account = db.get_account(ctx.author.id)

    if not account:
        await ctx.send("❌ You don't have an account! Please register first using the buttons in the account channel.")
        return

    success, key, message = db.generate_key_for_user(ctx.author.id)

    if success:
        # Assign verified role
        verified_role = ctx.guild.get_role(VERIFIED_ROLE_ID)

        embed = discord.Embed(
            title="🎉 Your Product Key",
            description=f"Your key has been generated successfully!",
            color=0x2ECC71
        )
        embed.add_field(name="🔑 Key", value=f"`{key}`", inline=False)
        embed.add_field(name="Product", value="Premium Access", inline=True)
        embed.add_field(name="Duration", value="30 days", inline=True)
        embed.add_field(
            name="⚠️ Important",
            value="Save this key! You can only generate one key per account.",
            inline=False
        )

        # Try to DM the user
        try:
            await ctx.author.send(embed=embed)
            await ctx.send(f"✅ {ctx.author.mention} Check your DMs for your product key!", delete_after=10)
        except discord.Forbidden:
            await ctx.send(embed=embed, delete_after=60)
            await ctx.send(
                f"⚠️ {ctx.author.mention} Please enable DMs! Your key will be deleted in 60 seconds for security.",
                delete_after=10)

        # Assign verified role
        if verified_role:
            try:
                await ctx.author.add_roles(verified_role, reason="Generated product key")
                logger.info(f"Assigned {verified_role.name} to {ctx.author} ({ctx.author.id})")
            except discord.Forbidden:
                logger.error(f"Could not assign verified role to {ctx.author}")

        # Delete command message for security
        try:
            await ctx.message.delete()
        except:
            pass

        logger.info(f"User {ctx.author} ({ctx.author.id}) generated key: {key}")
    else:
        await ctx.send(f"❌ {message}", delete_after=10)
        try:
            await ctx.message.delete()
        except:
            pass


# ==================== ADMIN COMMANDS ====================

@bot.command(name='get_roles')
@commands.has_permissions(administrator=True)
async def get_roles(ctx):
    """List all roles with their IDs - USE THIS FIRST!"""
    embed = discord.Embed(title="🎭 Server Roles & IDs", color=0x5865F2)
    embed.description = "Copy the role IDs you need:\n\n"

    for role in ctx.guild.roles:
        embed.add_field(name=role.name, value=f"ID: `{role.id}`", inline=False)

    embed.set_footer(text="Update CUSTOMER_ROLE_ID and VERIFIED_ROLE_ID in your code")
    await ctx.send(embed=embed)


@bot.command(name='setup_channels')
@commands.has_permissions(administrator=True)
async def setup_channels(ctx):
    """Set up the registration and verification panels"""

    account_embed = discord.Embed(
        title="👤 Account Management",
        description="Create and manage your account here, then use `!generate_key` to get your product key.",
        color=0x5865F2
    )
    account_embed.add_field(name="📝 Register", value="Create a new account with your email and password", inline=False)
    account_embed.add_field(name="🔐 Login", value="View your account information", inline=False)
    account_embed.add_field(name="🔑 Reset Password", value="Change your account password", inline=False)
    account_embed.add_field(
        name="🎟️ Generate Key",
        value="After registering, type `!generate_key` to get your product key and verified role!",
        inline=False
    )

    verify_embed = discord.Embed(
        title="🎟️ Redeem Admin Key",
        description="If an admin gave you a special key, redeem it here.",
        color=0x2ECC71
    )
    verify_embed.add_field(
        name="Note:",
        value="Most users should use `!generate_key` instead of this option.",
        inline=False
    )

    await ctx.send(embed=account_embed, view=AccountView())
    await ctx.send(embed=verify_embed, view=VerificationView())

    try:
        await ctx.message.delete()
    except:
        pass

    logger.info(f"Setup completed in #{ctx.channel.name} by {ctx.author}")


@bot.command(name='announce')
@commands.has_permissions(administrator=True)
async def announce(ctx, channel: discord.TextChannel, *, message: str):
    """
    Send an announcement to a specific channel (admin only)
    Usage: !announce #channel Your message here
    """
    embed = discord.Embed(
        title="📢 Announcement",
        description=message,
        color=0x5865F2,
        timestamp=datetime.utcnow()
    )

    # Add footer with admin who posted
    if ctx.author.avatar:
        embed.set_footer(text=f"Posted by {ctx.author.name}", icon_url=ctx.author.avatar.url)
    else:
        embed.set_footer(text=f"Posted by {ctx.author.name}")

    try:
        await channel.send(embed=embed)
        await ctx.send(f"✅ Announcement sent to {channel.mention}", delete_after=5)

        # Delete the command message
        try:
            await ctx.message.delete()
        except:
            pass

        logger.info(f"Announcement sent to #{channel.name} by {ctx.author}")
    except discord.Forbidden:
        await ctx.send(f"❌ I don't have permission to send messages in {channel.mention}")
    except Exception as e:
        await ctx.send(f"❌ Error sending announcement: {str(e)}")
        logger.error(f"Error sending announcement: {e}")


@bot.command(name='admin_generate_key')
@commands.has_permissions(administrator=True)
async def admin_generate_key(ctx, product_name: str, duration_days: int = 30):
    """
    [ADMIN] Generate a product key manually
    Usage: !admin_generate_key "Product Name" 30
    """
    key = db.admin_generate_key(product_name, duration_days)

    embed = discord.Embed(title="🎟️ Admin Key Generated", color=0x2ECC71)
    embed.add_field(name="Key", value=f"`{key}`", inline=False)
    embed.add_field(name="Product", value=product_name, inline=True)
    embed.add_field(name="Duration", value=f"{duration_days} days", inline=True)
    embed.set_footer(text="Send this key to the customer privately - it needs to be redeemed")

    await ctx.send(embed=embed, delete_after=60)
    await ctx.message.delete()

    logger.info(f"Admin key generated: {key} for {product_name} by {ctx.author}")


@bot.command(name='check_account')
@commands.has_permissions(administrator=True)
async def check_account(ctx, user: discord.Member):
    """
    Check a user's account status
    Usage: !check_account @user
    """
    account = db.get_account(user.id)

    if not account:
        await ctx.send(f"❌ {user.mention} has no account registered.")
        return

    embed = discord.Embed(title=f"Account Info: {user.name}", color=0x5865F2)
    embed.add_field(name="Email", value=account['email'], inline=False)
    embed.add_field(name="Key Generated", value="✅ Yes" if account['key_generated'] else "❌ No", inline=True)
    embed.add_field(name="Active Key", value=account['key'] if account['key'] else "None", inline=True)
    embed.add_field(name="Created", value=account['created_at'][:10], inline=True)

    await ctx.send(embed=embed)


@bot.command(name='stats')
@commands.has_permissions(administrator=True)
async def stats(ctx):
    """Show database statistics"""
    total_accounts = len(db.accounts)
    keys_generated = sum(1 for acc in db.accounts.values() if acc['key_generated'])
    total_keys = len(db.keys)
    admin_keys = sum(1 for key in db.keys.values() if key['generated_by'] == 'admin')

    embed = discord.Embed(title="📊 System Statistics", color=0x5865F2)
    embed.add_field(name="Total Accounts", value=total_accounts, inline=True)
    embed.add_field(name="Users with Keys", value=keys_generated, inline=True)
    embed.add_field(name="Total Keys", value=total_keys, inline=True)
    embed.add_field(name="Admin Keys", value=admin_keys, inline=True)
    embed.add_field(name="User Keys", value=total_keys - admin_keys, inline=True)

    await ctx.send(embed=embed)


@bot.command(name='help', aliases=['commands', 'h'])
async def help_command(ctx):
    """Display available commands with descriptions"""

    if ctx.author.guild_permissions.administrator:
        embed = discord.Embed(
            title="🤖 Bot Commands",
            description="Here are all available commands:",
            color=0x5865F2
        )

        # User Commands Section
        embed.add_field(
            name="👥 User Commands",
            value=(
                "`!generate_key`\n"
                "└ Generate your product key after registering and logging in\n"
                "└ You can only generate one key per account\n"
            ),
            inline=False
        )

        # Admin Commands Section
        embed.add_field(
            name="🛡️ Admin Commands - Setup",
            value=(
                "`!get_roles`\n"
                "└ List all server roles with their IDs\n"
                "└ Use this to find role IDs for configuration\n\n"
                "`!setup_channels`\n"
                "└ Create account management and verification panels\n"
                "└ Run this in the channel where users will register\n"
            ),
            inline=False
        )

        embed.add_field(
            name="🛡️ Admin Commands - Announcements",
            value=(
                "`!announce #channel Your message`\n"
                "└ Send a formatted announcement to any channel\n"
                "└ Example: `!announce #updates New features added!`\n"
            ),
            inline=False
        )

        embed.add_field(
            name="🛡️ Admin Commands - Key Management",
            value=(
                "`!admin_generate_key \"Product Name\" 30`\n"
                "└ Generate a product key that needs to be redeemed\n"
                "└ Duration in days (default: 30)\n\n"
                "`!check_account @user`\n"
                "└ View a user's account information and key status\n"
            ),
            inline=False
        )

        embed.add_field(
            name="🛡️ Admin Commands - Statistics",
            value=(
                "`!stats`\n"
                "└ View database statistics\n"
                "└ Shows total accounts, keys generated, etc.\n"
            ),
            inline=False
        )

        embed.set_footer(text="💡 Tip: You can also use !commands or !h")
        await ctx.send(embed=embed)

    else:
        # Regular user help
        embed = discord.Embed(
            title="🤖 Available Commands",
            description="Here's what you can do:",
            color=0x5865F2
        )

        embed.add_field(
            name="📝 Getting Started",
            value=(
                "1️⃣ Register using the buttons in the account channel\n"
                "2️⃣ Login to verify your account\n"
                "3️⃣ Type `!generate_key` to get your product key\n"
            ),
            inline=False
        )

        embed.add_field(
            name="🔑 Generate Your Key",
            value=(
                "`!generate_key`\n"
                "└ Generate your personal product key\n"
                "└ You must be registered and logged in first\n"
                "└ You can only generate ONE key per account\n"
            ),
            inline=False
        )

        embed.add_field(
            name="ℹ️ Need Help?",
            value="Contact an admin if you have any issues!",
            inline=False
        )

        embed.set_footer(text="💡 Tip: You can also use !commands or !h")
        await ctx.send(embed=embed)


# ==================== RUN BOT ====================

if __name__ == "__main__":
    if not TOKEN:
        logger.error("DISCORD_TOKEN not found in .env file!")
        print("\n❌ ERROR: DISCORD_TOKEN not found!")
        print("Create a .env file with: DISCORD_TOKEN=your_token_here\n")
    else:
        try:
            print("\n🚀 Starting bot...")
            print("📋 Remember to:")
            print("   1. Run !get_roles to get role IDs")
            print("   2. Update CUSTOMER_ROLE_ID and VERIFIED_ROLE_ID in code")
            print("   3. Run !setup_channels\n")
            bot.run(TOKEN, log_handler=None)
        except Exception as e:
            logger.critical(f"Failed to start bot: {e}", exc_info=e)
