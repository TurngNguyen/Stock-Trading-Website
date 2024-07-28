import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
import datetime

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        db.execute("UPDATE users SET cash = cash + .01 WHERE id = ?", session["user_id"])
        return redirect("/")
    elif request.method == "GET":
        """Show portfolio of stocks"""
        user = db.execute("SELECT * FROM users WHERE id = ?", session["user_id"])[0]
        stocks = db.execute(("SELECT DISTINCT stock, stocks_owned.symbol, stocks_owned.quantity"
                             " FROM stocks_owned"
                             " INNER JOIN transactions"
                             " ON transactions.symbol = stocks_owned.symbol"
                             " WHERE stocks_owned.user_id = ?"
                             " ORDER BY stock ASC"), session["user_id"])
        # Add current price to each stock to display
        for stock in stocks:
            stock["current_price"] = lookup(stock["symbol"])["price"]
    
        # Calculate grand total
        grand_total = user["cash"]
        for stock in stocks:
            grand_total += stock["current_price"] * stock["quantity"]
    
        return render_template("index.html", user=user, stocks=stocks, grand_total=grand_total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "GET":
        return render_template("buy.html")
    elif request.method == "POST":

        # Ensure symbol was submitted
        if not request.form.get("symbol"):
            return apology("must provide symbol", 400)

        symbol = request.form.get("symbol").upper()

        # Ensure symbol exists
        if not lookup(symbol):
            return apology("symbol does not exist", 400)

        # Ensure shares was submitted
        if not request.form.get("shares"):
            return apology("shares not found", 400)

        shares = request.form.get("shares")

        # Ensure shares is an integer
        try:
            if float(shares).is_integer():
                shares = int(float(shares))
            else:
                return apology("shares is not an integer", 400)
        except:
            return apology("shares is not an integer", 400)

        # Ensure shares is a positive integer
        if not shares > 0:
            return apology("shares is not a positive integer", 400)

        # Check if user has enough money to buy
        user_cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]
        if user_cash < (lookup(symbol)["price"] * shares):
            return apology("insufficent funds", 400)

        # Record transaction in table
        db.execute("INSERT INTO transactions (user_id, type, stock, symbol, quantity, price, time) VALUES (?, 'buy', ?, ?, ?, ?, ?)",
                   session["user_id"],
                   lookup(symbol)["name"],
                   symbol,
                   shares,
                   lookup(symbol)["price"],
                   datetime.datetime.today().strftime("%m-%d-%y %H:%M:%S")
                   )

        # Insert / Update stocks owned by user
        if len(db.execute("SELECT * FROM stocks_owned WHERE user_id = ? AND symbol = ?", session["user_id"], symbol)) == 0:
            db.execute("INSERT INTO stocks_owned (user_id, symbol, quantity) VALUES (?, ?, ?)", session["user_id"], symbol, 0)
        db.execute("UPDATE stocks_owned SET quantity = quantity + ? WHERE user_id = ? AND symbol = ?",
                   shares, session["user_id"], symbol)

        # Update new balance
        purchase_price = lookup(symbol)["price"] * shares
        db.execute("UPDATE users SET cash = cash - ? WHERE id = ?", purchase_price, session["user_id"])

        return redirect("/")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    if request.method == "GET":
        user = db.execute("SELECT username FROM users WHERE id = ?", session["user_id"])[0]
        transactions = db.execute("SELECT * FROM transactions WHERE user_id = ?", session["user_id"])

        return render_template("history.html", user=user, transactions=transactions)

    elif request.method == "POST":
        return render_template("history.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "GET":
        return render_template("quote.html")
    elif request.method == "POST":

        # Ensure symbol was submitted
        if not request.form.get("symbol"):
            return apology("must provide symbol", 400)

        symbol = lookup(request.form.get("symbol").upper())

        # Ensure symbol is a valid stock
        if not symbol:
            return apology("not a valid symbol", 400)

        return render_template("quoted.html", stock=symbol)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "GET":
        return render_template("register.html")
    elif request.method == "POST":

        username = request.form.get("username")
        password = generate_password_hash(request.form.get("password"))

        # Ensure username was submitted
        if not username:
            return apology("must provide username", 400)

        # Ensure username is not in database
        if len(db.execute("SELECT * FROM users WHERE username = ?", username)) != 0:
            return apology("username taken", 400)

        # Ensure password was submitted
        if not request.form.get("password"):
            return apology("must provide password", 400)

        # Ensure password and confirmation match
        if request.form.get("password") != request.form.get("confirmation"):
            return apology("confirmation incorrect", 400)

        db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", username, password)
        return redirect("/login")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "GET":
        stocks = db.execute(("SELECT DISTINCT stocks_owned.user_id, stock, stocks_owned.symbol, stocks_owned.quantity"
                             " FROM stocks_owned"
                             " INNER JOIN transactions"
                             " ON transactions.symbol = stocks_owned.symbol"
                             " WHERE stocks_owned.user_id = ?"
                             " ORDER BY stock ASC"), session["user_id"])
        return render_template("sell.html", stocks=stocks)
    elif request.method == "POST":

        # Ensure symbol was submitted
        if not request.form.get("symbol"):
            return apology("must provide symbol", 400)

        symbol = request.form.get("symbol").upper()

        # Ensure shares was submitted
        if not request.form.get("shares"):
            return apology("must sell shares", 400)

        shares = request.form.get("shares")

        # Ensure shares is an integer
        try:
            if float(shares).is_integer():
                shares = int(float(shares))
            else:
                return apology("shares is not an integer", 400)
        except:
            return apology("shares is not an integer", 400)

        # Ensure shares is a positive integer
        if not shares > 0:
            return apology("shares is not a positive integer", 400)

        # Ensure symbol exists
        if not lookup(symbol):
            return apology("symbol does not exist", 400)

        # Check if user has enough stock to sell
        if db.execute("SELECT quantity FROM stocks_owned WHERE user_id = ? AND symbol = ?", session["user_id"], symbol)[0]["quantity"] < shares:
            return apology("must have enough shares", 400)

        # Record transaction in table
        db.execute("INSERT INTO transactions (user_id, type, stock, symbol, quantity, price, time) VALUES (?, 'sell', ?, ?, ?, ?, ?)",
                   session["user_id"],
                   lookup(symbol)["name"],
                   symbol,
                   shares,
                   lookup(symbol)["price"],
                   datetime.datetime.today().strftime("%m-%d-%y %H:%M:%S")
                   )

        # Update amount of stocks_owned. Delete column if quantity = 0
        db.execute("UPDATE stocks_owned SET quantity = quantity - ? WHERE user_id = ? AND symbol = ?",
                   shares, session["user_id"], symbol)
        db.execute("DELETE FROM stocks_owned WHERE user_id = ? AND symbol = ? AND quantity = 0", session["user_id"], symbol)

        # Update new balance
        sell_price = lookup(symbol)["price"] * shares
        db.execute("UPDATE users SET cash = cash + ? WHERE id = ?", sell_price, session["user_id"])

        return redirect("/")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
