# Shop Assistant Bot – User Guide

## Default behavior

**If you don’t specify a command, the bot treats your message as a Low Stock request.**  
Example: `Almond 2` is handled like `Low Almond 2` and adds 2 Almonds to the shopping list.

---

## Commands

### Single item (default)

| You send | Action |
|----------|--------|
| `Low Milk` | Add 1 Milk (new or existing item) |
| `Low Almond 2` | Add 2 Almonds |
| `Milk 3` | Same as Low – add 3 Milk (default = Low) |
| `Beans` | Add 1 Beans |


### New items

- **New items must be added with the `Low` command.**
- If you send an item name **without** `Low` and it’s not in the list yet, the bot asks: *“Add as new item? Reply yes or no.”*
- Reply **yes**, **y**, or **ye** to add it.
- The bot first asks for **type**: reply **1** = Raw (raw product), **2** = Prep (prepared item).
- If you choose **Prep**, the item is added with the default prep supplier (no supplier selection).
- If you choose **Raw**, the bot shows a **numbered supplier list** – reply with a number.
- Reply **no**, **n**, or **!** to cancel.

### Item type

Each item has a type: **Raw** (raw product) or **Prep** (prepared item). When adding a new item, you choose the type after selecting a supplier (or if there are no suppliers).

### Language

| You send | Action |
|----------|--------|
| `Lang` | Show supported languages (English, עברית) and ask for selection. Reply 1 or 2. |

The selected language is used for all bot replies and messages.

### Set required quantity (ordering)

| You send | Action |
|----------|--------|
| `Need Milk 10` | Set required quantity for Milk to 10 |
| `N Milk 10` | Same (short form) |
| `צריך חלב 10` / `צ חלב 10` | Same (Hebrew) |

The items list shows **quantity/required** (e.g. `3/10`). If no required quantity is set, it shows `-` (e.g. `3/-`).

### Edit item

| You send | Action |
|----------|--------|
| `Edit Milk` | Open edit menu for Milk |
| `E Milk` | Same (short form) |
| `ערוך חלב` / `ער חלב` | Same (Hebrew) |

Edit menu options:
1. **Change supplier** – pick from supplier list
2. **Change type** – Raw or Prep
3. **Rename** – enter new name
4. **Delete** – confirm with yes/no

### Hebrew commands (when language is עברית)

In Hebrew mode, you can use Hebrew commands:

| English | Hebrew (full) | Short |
|---------|---------------|-------|
| Low | פריט | פ |
| Sup | ספק | ס |
| Supa | ספקחדש | סח |
| List | מלאי | מ |
| ListExt | מלאימורחב | ממ |
| Need | צריך | צ |
| Edit | ערוך | ער |
| Help | עזרה | ע |

### Help

| You send | Action |
|----------|--------|
| `Help` / `ע` | Show all commands |

### Supplier management

| You send | Action |
|----------|--------|
| `List` / `מ` | List all items (name, qty/required, type, supplier) |
| `ListExt` / `ממ` / `מלאימורחב` | Extended list: items + last report date + user who updated |
| `Edit Milk` / `E Milk` / `ערוך חלב` / `ער חלב` | Edit item (supplier, type, name, delete) |
| `Need Milk 10` / `N Milk 10` / `צריך חלב 10` / `צ חלב 10` | Set required quantity for an item |
| `Sup` / `ס` | List all suppliers (company, contact, number) |
| `Supa` / `סח` | Add a new supplier – bot asks: company name, contact name, contact number |

### Multi-item mode

| You send | Action |
|----------|--------|
| `Lows` | Start multi-item mode |
| `Lows Milk` | Start and add Milk as first item |
| `Milk 2` | Add another item (while in multi mode) |
| `!` | End multi-item mode and save all items |

**Important:** In multi-item mode, only **existing** items are allowed.  
If you send a new item, the bot replies: *“X is not in the list. Add it first with 'Low X'.”*

### Reserved: `!`

- `!` is **not** an item name.
- In single mode: if you type `!` by mistake, the bot explains that `!` is reserved.
- In multi mode: `!` ends the mode and saves all items.
- When asked “Add as new item?”: `!` cancels.

---

## Quick reference

| Message | Meaning |
|---------|---------|
| `Low X` / `פ X` | Add X (new or existing) |
| `X` or `X 2` | Same as Low (default) |
| `Help` / `ע` | Show all commands |
| `Lang` | Change language (English / עברית) |
| `List` / `מ` | List all items (name, qty/required, type, supplier) |
| `ListExt` / `ממ` | Extended list (last report date, user) |
| `Edit Milk` / `E Milk` / `ער חלב` | Edit item (supplier, type, name, delete) |
| `Need X N` / `N X N` / `צ X N` | Set required quantity for item X |
| `Sup` / `ס` | List suppliers |
| `Supa` / `סח` | Add a supplier (company, contact, number) |
| `Lows` | Multi-item mode – add several existing items |
| `!` | End multi-item mode, or cancel |
