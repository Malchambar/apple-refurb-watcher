on run argv
    if (count of argv) is less than 2 then
        error "Usage: osascript send_imessage.scpt <recipient> <message>"
    end if

    set recipientHandle to item 1 of argv
    set messageText to item 2 of argv

    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy recipientHandle of targetService
        send messageText to targetBuddy
    end tell
end run
