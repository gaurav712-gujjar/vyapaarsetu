# ============================================================
# VyapaarSetu - Delete old products, then bulk-add 20 per
# category with keyword-relevant images.
# ============================================================

$AdminEmail    = "gaurav@gmail.com"
$AdminPassword = "Gaurav@712"
$BaseUrl       = "http://localhost:8000"

$loginBody = @{ email = $AdminEmail; password = $AdminPassword } | ConvertTo-Json
$loginResp = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method POST -ContentType "application/json" -Body $loginBody
$token = $loginResp.access_token
$headers = @{ Authorization = "Bearer $token" }
Write-Host "Logged in." -ForegroundColor Green

# ---- Step 1: delete existing products ----
$existing = Invoke-RestMethod -Uri "$BaseUrl/api/products" -Method GET
Write-Host "Deleting $($existing.Count) existing products..." -ForegroundColor Yellow
foreach ($p in $existing) {
    try {
        Invoke-RestMethod -Uri "$BaseUrl/api/admin/products/$($p.id)" -Method DELETE -Headers $headers | Out-Null
    } catch {}
}
Write-Host "Old products removed." -ForegroundColor Yellow

# ---- Step 2: get categories ----
$categories = Invoke-RestMethod -Uri "$BaseUrl/api/categories" -Method GET
$catMap = @{}
foreach ($c in $categories) { $catMap[$c.name] = $c.id }
Write-Host "Categories:" ($catMap.Keys -join ", ")

# ---- Step 3: product data with matching image keywords ----
$products = @{
    "Clothing" = @(
        @{ name = "Cotton Block-Print Kurta"; price = 899; kw = "kurta" },
        @{ name = "Handwoven Silk Saree"; price = 3499; kw = "silksaree" },
        @{ name = "Embroidered Anarkali Suit"; price = 2199; kw = "anarkali" },
        @{ name = "Denim Jacket"; price = 1599; kw = "denimjacket" },
        @{ name = "Linen Casual Shirt"; price = 1099; kw = "linenshirt" },
        @{ name = "Printed Palazzo Set"; price = 1299; kw = "palazzopants" },
        @{ name = "Chikankari Kurti"; price = 999; kw = "kurti" },
        @{ name = "Woolen Shawl"; price = 1799; kw = "shawl" },
        @{ name = "Nehru Jacket"; price = 1499; kw = "nehrujacket" },
        @{ name = "Cotton Dupatta"; price = 399; kw = "dupatta" },
        @{ name = "Bandhani Print Dress"; price = 1699; kw = "bandhanidress" },
        @{ name = "Khadi Cotton Kurta"; price = 799; kw = "khadikurta" },
        @{ name = "Ikat Print Kurti"; price = 949; kw = "ikatprint" },
        @{ name = "Floral Maxi Dress"; price = 1399; kw = "maxidress" },
        @{ name = "Formal Cotton Shirt"; price = 999; kw = "cottonshirt" },
        @{ name = "Jaipuri Print Palazzo"; price = 899; kw = "jaipuriprint" },
        @{ name = "Zari Border Saree"; price = 2899; kw = "zarisaree" },
        @{ name = "Kids Ethnic Kurta Set"; price = 699; kw = "kidsethnicwear" },
        @{ name = "Men's Pathani Suit"; price = 1299; kw = "pathanisuit" },
        @{ name = "Embroidered Shrug"; price = 799; kw = "shrug" }
    )
    "Sweets" = @(
        @{ name = "Kaju Katli (500g)"; price = 599; kw = "kajukatli" },
        @{ name = "Besan Ladoo (500g)"; price = 349; kw = "besanladoo" },
        @{ name = "Motichoor Ladoo (500g)"; price = 379; kw = "motichoorladoo" },
        @{ name = "Gulab Jamun (12 pcs)"; price = 299; kw = "gulabjamun" },
        @{ name = "Rasgulla (12 pcs)"; price = 279; kw = "rasgulla" },
        @{ name = "Soan Papdi (500g)"; price = 249; kw = "soanpapdi" },
        @{ name = "Mysore Pak (500g)"; price = 449; kw = "mysorepak" },
        @{ name = "Rasmalai (6 pcs)"; price = 329; kw = "rasmalai" },
        @{ name = "Coconut Barfi (500g)"; price = 349; kw = "coconutbarfi" },
        @{ name = "Dry Fruit Chikki (500g)"; price = 399; kw = "chikki" },
        @{ name = "Peda (500g)"; price = 329; kw = "peda" },
        @{ name = "Anjeer Barfi (500g)"; price = 599; kw = "anjeerbarfi" },
        @{ name = "Kalakand (500g)"; price = 399; kw = "kalakand" },
        @{ name = "Til Ladoo (500g)"; price = 299; kw = "tilladoo" },
        @{ name = "Milk Cake (500g)"; price = 449; kw = "milkcake" },
        @{ name = "Badam Halwa (500g)"; price = 649; kw = "badamhalwa" },
        @{ name = "Jalebi (500g)"; price = 249; kw = "jalebi" },
        @{ name = "Petha (500g)"; price = 199; kw = "petha" },
        @{ name = "Dry Fruit Ladoo (500g)"; price = 549; kw = "dryfruitladoo" },
        @{ name = "Chocolate Barfi (500g)"; price = 399; kw = "chocolatebarfi" }
    )
    "Home-cooked Food" = @(
        @{ name = "Homemade Aam Papad (250g)"; price = 199; kw = "aampapad" },
        @{ name = "Homemade Mango Pickle (500g)"; price = 249; kw = "mangopickle" },
        @{ name = "Homemade Mixed Veg Pickle (500g)"; price = 229; kw = "vegpickle" },
        @{ name = "Homemade Papad (250g)"; price = 149; kw = "papad" },
        @{ name = "Homemade Masala Chana (250g)"; price = 179; kw = "masalachana" },
        @{ name = "Homemade Namkeen Mix (500g)"; price = 299; kw = "namkeen" },
        @{ name = "Homemade Bhakarwadi (250g)"; price = 219; kw = "bhakarwadi" },
        @{ name = "Homemade Chakli (250g)"; price = 199; kw = "chakli" },
        @{ name = "Homemade Sev (250g)"; price = 149; kw = "sevsnack" },
        @{ name = "Homemade Ghee (500ml)"; price = 599; kw = "ghee" },
        @{ name = "Homemade Masala Powder Combo"; price = 349; kw = "spicepowder" },
        @{ name = "Homemade Sattu Powder (500g)"; price = 199; kw = "sattu" },
        @{ name = "Homemade Wheat Laddu (500g)"; price = 279; kw = "wheatladdu" },
        @{ name = "Homemade Dal Vadi (250g)"; price = 189; kw = "dalvadi" },
        @{ name = "Homemade Karela Chips (200g)"; price = 159; kw = "vegetablechips" },
        @{ name = "Homemade Banana Chips (250g)"; price = 179; kw = "bananachips" },
        @{ name = "Homemade Thepla (10 pcs)"; price = 199; kw = "thepla" },
        @{ name = "Homemade Chutney Combo (3 jars)"; price = 349; kw = "chutney" },
        @{ name = "Homemade Rice Papad (250g)"; price = 169; kw = "ricepapad" },
        @{ name = "Homemade Til Chikki (250g)"; price = 199; kw = "tilchikki" }
    )
    "Handicrafts" = @(
        @{ name = "Handpainted Terracotta Pot"; price = 499; kw = "terracottapot" },
        @{ name = "Wooden Elephant Showpiece"; price = 799; kw = "woodenelephant" },
        @{ name = "Madhubani Painting"; price = 1299; kw = "madhubanipainting" },
        @{ name = "Brass Diya Set (6 pcs)"; price = 599; kw = "brassdiya" },
        @{ name = "Jute Wall Hanging"; price = 449; kw = "jutewallhanging" },
        @{ name = "Blue Pottery Vase"; price = 899; kw = "bluepottery" },
        @{ name = "Handwoven Cane Basket"; price = 599; kw = "canebasket" },
        @{ name = "Wooden Jewellery Box"; price = 749; kw = "woodenjewellerybox" },
        @{ name = "Rajasthani Puppet Pair"; price = 399; kw = "rajasthanipuppet" },
        @{ name = "Macrame Wall Hanging"; price = 649; kw = "macrame" },
        @{ name = "Handcrafted Bamboo Lamp"; price = 899; kw = "bamboolamp" },
        @{ name = "Clay Wind Chime"; price = 349; kw = "windchime" },
        @{ name = "Embroidered Cushion Cover"; price = 399; kw = "cushioncover" },
        @{ name = "Warli Art Frame"; price = 699; kw = "warliart" },
        @{ name = "Handmade Paper Notebook Set"; price = 249; kw = "handmadenotebook" },
        @{ name = "Dhokra Art Figurine"; price = 999; kw = "dhokraart" },
        @{ name = "Wooden Coasters Set (6 pcs)"; price = 349; kw = "woodencoasters" },
        @{ name = "Handwoven Table Runner"; price = 499; kw = "tablerunner" },
        @{ name = "Marble Inlay Coaster Set"; price = 799; kw = "marbleinlay" },
        @{ name = "Recycled Fabric Door Mat"; price = 299; kw = "doormat" }
    )
}

$successCount = 0
$failCount = 0
$globalIndex = 1

foreach ($catName in $products.Keys) {
    if (-not $catMap.ContainsKey($catName)) {
        Write-Host "Category '$catName' not found, skipping." -ForegroundColor Yellow
        continue
    }
    $catId = $catMap[$catName]
    $index = 1
    foreach ($p in $products[$catName]) {
        $imageUrl = "https://loremflickr.com/600/400/$($p.kw)?lock=$globalIndex"
        $body = @{
            category_id = $catId
            name        = $p.name
            price       = $p.price
            stock       = 25
            description = "$($p.name) - handpicked quality, freshly sourced."
            image_url   = $imageUrl
        } | ConvertTo-Json

        try {
            Invoke-RestMethod -Uri "$BaseUrl/api/admin/products" -Method POST -Headers $headers -ContentType "application/json" -Body $body | Out-Null
            Write-Host "[$catName $index/20] Added: $($p.name)" -ForegroundColor Green
            $successCount++
        } catch {
            Write-Host "[$catName $index/20] FAILED: $($p.name)" -ForegroundColor Red
            $failCount++
        }
        $index++
        $globalIndex++
    }
}

Write-Host ""
Write-Host "Done. Success: $successCount, Failed: $failCount" -ForegroundColor Cyan