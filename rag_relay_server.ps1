Add-Type -AssemblyName System.Net.Http

$ListenPort = 30002
$ChatUrl = "http://10.103.201.164:8000/api/rag/chat"
$RegisterUrl = "http://10.103.201.164:8000/api/posts/request"
$ImageChatUrl = "http://10.103.201.164:8000/api/rag/image-chat"
$FeedbackUrl = "http://10.103.201.164:8000/api/logs/help-yn"
$ItemSearchUrl = "http://10.103.201.164:8000/api/items/search"
$PosMasterUrl = "http://10.103.201.164:8000/tools/create_pos_master"
$PatternSearchUrl = "http://10.103.201.164:8000/tools/pattern_lookup"
$PatternUpdateUrl = "http://10.103.201.164:8000/tools/pattern_update"
$RefundStatusUrl = "http://10.103.201.164:8000/tools/refund_status"
$RefundCancelUrl = "http://10.103.201.164:8000/tools/refund_cancel"
$FamilySaleUrl = "http://10.103.201.164:8000/tools/family_sale_sales"
$TopFaqQuestionsUrl = "http://10.103.201.164:8000/api/faqs/top-questions"

$Utf8 = New-Object System.Text.UTF8Encoding($false)
$Listener = New-Object System.Net.HttpListener
$Listener.Prefixes.Add("http://+:$ListenPort/")

$HttpClient = New-Object System.Net.Http.HttpClient
$HttpClient.Timeout = [TimeSpan]::FromSeconds(120)

function Send-JsonResponse {
    param(
        [System.Net.HttpListenerResponse]$Response,
        [int]$StatusCode,
        [string]$JsonBody
    )

    if ([string]::IsNullOrWhiteSpace($JsonBody)) {
        $JsonBody = "{}"
    }

    [byte[]]$Bytes = $Utf8.GetBytes($JsonBody)
    $Response.StatusCode = $StatusCode
    $Response.ContentType = "application/json; charset=utf-8"
    $Response.ContentEncoding = $Utf8
    $Response.ContentLength64 = $Bytes.Length

    try {
        $Response.OutputStream.Write($Bytes, 0, $Bytes.Length)
    }
    finally {
        $Response.OutputStream.Close()
    }
}

function Invoke-JsonPost {
    param(
        [string]$Url,
        [string]$JsonBody
    )

    $Content = New-Object System.Net.Http.StringContent(
        $JsonBody,
        [System.Text.Encoding]::UTF8,
        "application/json"
    )

    try {
        $Result = $HttpClient.PostAsync($Url, $Content).GetAwaiter().GetResult()
        $Body = $Result.Content.ReadAsStringAsync().GetAwaiter().GetResult()

        return [ordered]@{
            StatusCode = [int]$Result.StatusCode
            Body = [string]$Body
        }
    }
    finally {
        $Content.Dispose()
    }
}

function Invoke-BinaryPost {
    param(
        [string]$Url,
        [byte[]]$Body,
        [string]$ContentType
    )

    $Content = New-Object System.Net.Http.ByteArrayContent -ArgumentList (, $Body)

    try {
        $null = $Content.Headers.TryAddWithoutValidation(
            "Content-Type",
            $ContentType
        )

        $Result = $HttpClient.PostAsync($Url, $Content).GetAwaiter().GetResult()
        $ResponseBody = $Result.Content.ReadAsStringAsync().GetAwaiter().GetResult()

        return [ordered]@{
            StatusCode = [int]$Result.StatusCode
            Body = [string]$ResponseBody
        }
    }
    finally {
        $Content.Dispose()
    }
}

try {
    $Listener.Start()

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "Teams internal relay started"
    Write-Host "Listen   : http://+:$ListenPort/"
    Write-Host "Chat     : $ChatUrl"
    Write-Host "Register : $RegisterUrl"
    Write-Host "Image    : $ImageChatUrl"
    Write-Host "Feedback : $FeedbackUrl"
    Write-Host "Item     : $ItemSearchUrl"
    Write-Host "PosMaster: $PosMasterUrl"
    Write-Host "Pattern  : $PatternSearchUrl"
    Write-Host "PtnUpdate: $PatternUpdateUrl"
    Write-Host "Refund   : $RefundStatusUrl"
    Write-Host "RfndCancel: $RefundCancelUrl"
    Write-Host "FamilySale: $FamilySaleUrl"
    Write-Host "Top FAQ  : $TopFaqQuestionsUrl"
    Write-Host "Stop     : Ctrl+C"
    Write-Host "============================================================"

    while ($Listener.IsListening) {
        $Context = $Listener.GetContext()
        $Request = $Context.Request
        $Response = $Context.Response

        try {
            $Path = $Request.Url.AbsolutePath.ToLowerInvariant()
            $Method = $Request.HttpMethod.ToUpperInvariant()
            $Now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

            Write-Host ""
            Write-Host "[$Now] request"
            Write-Host "Client : $($Request.RemoteEndPoint)"
            Write-Host "Method : $Method"
            Write-Host "Path   : $Path"

            if (($Method -eq "GET") -and ($Path -eq "/health")) {
                $HealthBody = [ordered]@{
                    success = $true
                    service = "internal-relay"
                    listenPort = $ListenPort
                    chatUrl = $ChatUrl
                    registerUrl = $RegisterUrl
                    imageUrl = $ImageChatUrl
                    feedbackUrl = $FeedbackUrl
                    itemSearchUrl = $ItemSearchUrl
                    posMasterUrl = $PosMasterUrl
                    patternSearchUrl = $PatternSearchUrl
                    patternUpdateUrl = $PatternUpdateUrl
                    refundStatusUrl = $RefundStatusUrl
                    refundCancelUrl = $RefundCancelUrl
                    familySaleUrl = $FamilySaleUrl
                    topFaqQuestionsUrl = $TopFaqQuestionsUrl
                    serverTime = $Now
                } | ConvertTo-Json -Depth 10 -Compress

                Send-JsonResponse -Response $Response -StatusCode 200 -JsonBody $HealthBody
                continue
            }

            if ($Method -ne "POST") {
                $ErrorBody = [ordered]@{
                    success = $false
                    requestId = $null
                    message = "POST only"
                    errorCode = "METHOD_NOT_ALLOWED"
                } | ConvertTo-Json -Compress

                Send-JsonResponse -Response $Response -StatusCode 405 -JsonBody $ErrorBody
                continue
            }

            if (
                ($Path -eq "/image-chat") -or
                ($Path -eq "/api/items/search")
            ) {
                $IncomingContentType = [string]$Request.ContentType

                if ($Path -eq "/api/items/search") {
                    $BinaryTargetUrl = $ItemSearchUrl
                    $BinaryRouteName = "items-search"
                }
                else {
                    $BinaryTargetUrl = $ImageChatUrl
                    $BinaryRouteName = "image-chat"
                }

                if ([string]::IsNullOrWhiteSpace($IncomingContentType)) {
                    throw "Missing Content-Type"
                }

                if ($IncomingContentType -notmatch "multipart/form-data") {
                    throw "$BinaryRouteName requires multipart/form-data"
                }

                $MemoryStream = New-Object System.IO.MemoryStream

                try {
                    $Request.InputStream.CopyTo($MemoryStream)
                    [byte[]]$RawBody = $MemoryStream.ToArray()
                }
                finally {
                    $MemoryStream.Dispose()
                }

                if (($null -eq $RawBody) -or ($RawBody.Length -eq 0)) {
                    throw "Empty $BinaryRouteName request body"
                }

                Write-Host "Target : $BinaryTargetUrl"
                Write-Host "Type   : $IncomingContentType"
                Write-Host "Bytes  : $($RawBody.Length)"

                $BinaryResult = Invoke-BinaryPost `
                    -Url $BinaryTargetUrl `
                    -Body $RawBody `
                    -ContentType $IncomingContentType

                Send-JsonResponse `
                    -Response $Response `
                    -StatusCode $BinaryResult.StatusCode `
                    -JsonBody $BinaryResult.Body

                continue
            }

            $RequestEncoding = $Request.ContentEncoding
            if ($null -eq $RequestEncoding) {
                $RequestEncoding = $Utf8
            }

            $Reader = New-Object System.IO.StreamReader(
                $Request.InputStream,
                $RequestEncoding
            )

            try {
                $RequestBody = $Reader.ReadToEnd()
            }
            finally {
                $Reader.Close()
            }

            if ([string]::IsNullOrWhiteSpace($RequestBody)) {
                throw "Empty request body"
            }

            Write-Host "Raw JSON : $RequestBody"

            try {
                $Incoming = $RequestBody | ConvertFrom-Json
            }
            catch {
                throw "Invalid JSON: $($_.Exception.Message)"
            }

            if ($Path -eq "/faq-register") {
                $TargetUrl = $RegisterUrl
                $ForwardBody = [ordered]@{
                    source = [string]$Incoming.source
                    teamsUserId = [string]$Incoming.teamsUserId
                    teamsUserName = [string]$Incoming.teamsUserName
                    category = [string]$Incoming.category
                    question = [string]$Incoming.question
                    answer = [string]$Incoming.answer
                    keywords = [string]$Incoming.keywords
                    requestTime = [string]$Incoming.requestTime
                } | ConvertTo-Json -Depth 20 -Compress
            }
            elseif ($Path -eq "/tools/create_pos_master") {
                $TargetUrl = $PosMasterUrl

                $PosNo = ([string]$Incoming.posNo).Trim()
                $RequestedBy = ([string]$Incoming.requestedBy).Trim()

                if ([string]::IsNullOrWhiteSpace($PosNo)) {
                    throw "Missing posNo"
                }

                if ($PosNo.Length -gt 1000) {
                    throw "posNo must be 1000 characters or less"
                }

                if ($PosNo.Contains(",")) {
                    if ($PosNo.Contains("~") -or $PosNo.Contains("-")) {
                        throw "posNo list and range formats cannot be mixed"
                    }

                    foreach ($PosNumber in $PosNo.Split(",")) {
                        if ($PosNumber.Trim() -notmatch "^\d+$") {
                            throw "Invalid posNo list format"
                        }
                    }
                }
                elseif ($PosNo -match "^(\d+)\s*[~-]\s*(\d+)$") {
                    $RangeStart = 0L
                    $RangeEnd = 0L

                    if (-not [long]::TryParse($Matches[1], [ref]$RangeStart)) {
                        throw "Invalid range start"
                    }

                    if (-not [long]::TryParse($Matches[2], [ref]$RangeEnd)) {
                        throw "Invalid range end"
                    }

                    if ($RangeStart -gt $RangeEnd) {
                        throw "posNo range must be ascending"
                    }
                }
                elseif ($PosNo -notmatch "^\d+$") {
                    throw "Invalid posNo format"
                }

                $PosMasterPayload = [ordered]@{
                    posNo = $PosNo
                }

                if (-not [string]::IsNullOrWhiteSpace($RequestedBy)) {
                    $PosMasterPayload["requestedBy"] = $RequestedBy
                }

                $ForwardBody = $PosMasterPayload |
                    ConvertTo-Json -Depth 20 -Compress
            }
            elseif ($Path -eq "/tools/pattern_lookup") {
                $TargetUrl = $PatternSearchUrl

                $PosNo = [string]$Incoming.posNo
                $SearchType = [string]$Incoming.searchType
                $SearchValue = [string]$Incoming.searchValue
                $PageValue = $Incoming.page

                if ([string]::IsNullOrWhiteSpace($PosNo)) {
                    throw "Missing posNo"
                }

                $ForwardSearchType = $null
                if (-not [string]::IsNullOrWhiteSpace($SearchType)) {
                    if (($SearchType -ne "0") -and ($SearchType -ne "1")) {
                        throw "searchType must be null, 0 or 1"
                    }

                    $ForwardSearchType = $SearchType
                }

                $Page = 0
                if (-not [int]::TryParse([string]$PageValue, [ref]$Page)) {
                    throw "page must be an integer"
                }

                if ($Page -lt 1) {
                    throw "page must be 1 or greater"
                }

                $ForwardBody = [ordered]@{
                    posNo = $PosNo.Trim()
                    searchType = $ForwardSearchType
                    searchValue = $SearchValue.Trim()
                    page = $Page
                } | ConvertTo-Json -Depth 20 -Compress
            }
            elseif ($Path -eq "/tools/pattern_update") {
                $TargetUrl = $PatternUpdateUrl

                $PatternGroupCode = [string]$Incoming.patternGroupCode
                $PatternCode = [string]$Incoming.patternCode
                $PatternValue = [string]$Incoming.patternValue
                $UserId = [string]$Incoming.userId

                if ([string]::IsNullOrWhiteSpace($UserId)) {
                    throw "Missing userId"
                }

                if ([string]::IsNullOrWhiteSpace($PatternGroupCode)) {
                    throw "Missing patternGroupCode"
                }

                if ([string]::IsNullOrWhiteSpace($PatternCode)) {
                    throw "Missing patternCode"
                }

                if ([string]::IsNullOrWhiteSpace($PatternValue)) {
                    throw "Missing patternValue"
                }

                $ForwardBody = [ordered]@{
                    userId = $UserId.Trim()
                    patternGroupCode = $PatternGroupCode.Trim()
                    patternCode = $PatternCode.Trim()
                    patternValue = $PatternValue.Trim()
                } | ConvertTo-Json -Depth 20 -Compress
            }
            elseif (
                ($Path -eq "/tools/refund_status") -or
                ($Path -eq "/tools/refund_cancel")
            ) {
                if ($Path -eq "/tools/refund_cancel") {
                    $TargetUrl = $RefundCancelUrl
                }
                else {
                    $TargetUrl = $RefundStatusUrl
                }

                $StoreCode = ([string]$Incoming.storeCode).Trim()
                $SaleDate = ([string]$Incoming.saleDate).Trim()
                $PosNo = ([string]$Incoming.posNo).Trim()
                $DealNo = ([string]$Incoming.dealNo).Trim()

                if ([string]::IsNullOrWhiteSpace($StoreCode)) {
                    throw "Missing storeCode"
                }
                if ($SaleDate -notmatch "^\d{8}$") {
                    throw "saleDate must be YYYYMMDD"
                }
                if ([string]::IsNullOrWhiteSpace($PosNo)) {
                    throw "Missing posNo"
                }
                if ([string]::IsNullOrWhiteSpace($DealNo)) {
                    throw "Missing dealNo"
                }

                $ForwardBody = [ordered]@{
                    storeCode = $StoreCode
                    saleDate = $SaleDate
                    posNo = $PosNo
                    dealNo = $DealNo
                } | ConvertTo-Json -Depth 20 -Compress
            }
            elseif ($Path -eq "/tools/family_sale_sales") {
                $TargetUrl = $FamilySaleUrl

                $SearchType = ([string]$Incoming.searchType).Trim()
                if (($SearchType -ne "recent_hour") -and ($SearchType -ne "custom") -and ($SearchType -ne "single") -and ($SearchType -ne "fixed")) {
                    throw "searchType must be recent_hour, custom, single or fixed"
                }

                $Page = 1
                if ($null -ne $Incoming.page) {
                    if (-not [int]::TryParse([string]$Incoming.page, [ref]$Page)) {
                        throw "page must be an integer"
                    }
                }
                if ($Page -lt 1) {
                    throw "page must be 1 or greater"
                }

                $PageSize = 10
                if ($null -ne $Incoming.pageSize) {
                    if (-not [int]::TryParse([string]$Incoming.pageSize, [ref]$PageSize)) {
                        throw "pageSize must be an integer"
                    }
                }
                if (($PageSize -lt 1) -or ($PageSize -gt 20)) {
                    throw "pageSize must be between 1 and 20"
                }

                $ForwardPayload = [ordered]@{
                    searchType = $SearchType
                    page = $Page
                    pageSize = $PageSize
                }
                if (($SearchType -eq "custom") -or ($SearchType -eq "single") -or ($SearchType -eq "fixed")) {
                    $StartDateTime = ([string]$Incoming.startDateTime).Trim()
                    $EndDateTime = ([string]$Incoming.endDateTime).Trim()
                    if ([string]::IsNullOrWhiteSpace($StartDateTime)) {
                        throw "Missing startDateTime"
                    }
                    if ([string]::IsNullOrWhiteSpace($EndDateTime)) {
                        throw "Missing endDateTime"
                    }
                    $ForwardPayload["startDateTime"] = $StartDateTime
                    $ForwardPayload["endDateTime"] = $EndDateTime
                    if (($SearchType -eq "fixed") -or ($SearchType -eq "single")) {
                        $DisplayEndDateTime = ([string]$Incoming.displayEndDateTime).Trim()
                        if (-not [string]::IsNullOrWhiteSpace($DisplayEndDateTime)) {
                            $ForwardPayload["displayEndDateTime"] = $DisplayEndDateTime
                        }
                    }
                }

                $ForwardBody = $ForwardPayload | ConvertTo-Json -Depth 20 -Compress
            }
            elseif ($Path -eq "/api/logs/help-yn") {
                $TargetUrl = $FeedbackUrl

                $RegDt = [string]$Incoming.regDt
                $HelpYn = [string]$Incoming.helpYn
                $SeqValue = $Incoming.seq

                if ([string]::IsNullOrWhiteSpace($RegDt)) {
                    throw "Missing regDt"
                }

                if ($null -eq $SeqValue) {
                    throw "Missing seq"
                }

                $Seq = 0
                if (-not [int]::TryParse([string]$SeqValue, [ref]$Seq)) {
                    throw "seq must be an integer"
                }

                if (($HelpYn -ne "0") -and ($HelpYn -ne "1")) {
                    throw "helpYn must be 0 or 1"
                }

				$ForwardBody = [ordered]@{
				   regDt        = $RegDt
				   seq          = $Seq
				   helpYn       = $HelpYn
				   feedbackText = [string]$Incoming.feedbackText
				} | ConvertTo-Json -Depth 20 -Compress
            }
            elseif ($Path -eq "/api/faqs/top-questions") {
                $TargetUrl = $TopFaqQuestionsUrl

                $Category = ([string]$Incoming.category).Trim()
                if ($Category -notmatch "^[1-6]$") {
                    throw "category must be one of 1, 2, 3, 4, 5 or 6"
                }

                $Limit = 5
                if ($null -ne $Incoming.limit) {
                    if (-not [int]::TryParse([string]$Incoming.limit, [ref]$Limit)) {
                        throw "limit must be an integer"
                    }
                }

                if (($Limit -lt 1) -or ($Limit -gt 5)) {
                    throw "limit must be between 1 and 5"
                }

                $ForwardBody = [ordered]@{
                    category = $Category
                    limit = $Limit
                } | ConvertTo-Json -Depth 20 -Compress
            }
            else {
                $TargetUrl = $ChatUrl

                $Question = [string]$Incoming.message
                if ([string]::IsNullOrWhiteSpace($Question)) {
                    $Question = [string]$Incoming.question
                }

                if ([string]::IsNullOrWhiteSpace($Question)) {
                    throw "Missing message or question"
                }

                $UserId = [string]$Incoming.user_id
                if ([string]::IsNullOrWhiteSpace($UserId)) {
                    $UserId = [string]$Incoming.userId
                }

                if ([string]::IsNullOrWhiteSpace($UserId)) {
                    $UserId = "teams-anonymous"
                }

                $ForwardBody = [ordered]@{
                    userId = $UserId
                    question = $Question
                } | ConvertTo-Json -Depth 20 -Compress
            }

            Write-Host "Target : $TargetUrl"
            Write-Host "JSON   : $ForwardBody"

            $JsonResult = Invoke-JsonPost -Url $TargetUrl -JsonBody $ForwardBody

            Write-Host "Status : $($JsonResult.StatusCode)"
            Write-Host "Body   : $($JsonResult.Body)"

            Send-JsonResponse `
                -Response $Response `
                -StatusCode $JsonResult.StatusCode `
                -JsonBody $JsonResult.Body

            continue
        }
        catch {
            $ErrorMessage = $_.Exception.Message
            Write-Host "Relay error: $ErrorMessage" -ForegroundColor Red

            $ErrorBody = [ordered]@{
                success = $false
                requestId = $null
                message = "Relay error: $ErrorMessage"
                errorCode = "RELAY_ERROR"
            } | ConvertTo-Json -Compress

            try {
                Send-JsonResponse `
                    -Response $Response `
                    -StatusCode 502 `
                    -JsonBody $ErrorBody
            }
            catch {
                Write-Host "Failed to send error response: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    }
}
finally {
    if (($null -ne $Listener) -and $Listener.IsListening) {
        $Listener.Stop()
    }

    if ($null -ne $Listener) {
        $Listener.Close()
    }

    if ($null -ne $HttpClient) {
        $HttpClient.Dispose()
    }

    Write-Host ""
    Write-Host "Relay stopped"
}
