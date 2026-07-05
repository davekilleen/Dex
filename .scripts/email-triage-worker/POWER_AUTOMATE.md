# Email Triage in Power Automate

Run email classification **directly in your Power Automate flow** without calling the Cloudflare Worker.

---

## Option 1: Compose Action (Simple)

Use a single **Compose** action to evaluate triage logic.

### Step 1: Add Compose Action

In your flow, add an action: **Data > Compose**

**Inputs:**
```
{
  "subject": @{triggerOutputs()['headers']['subject']},
  "from": @{triggerOutputs()['headers']['from']},
  "body": @{body('Get_email_body')},
  "date": @{triggerOutputs()['headers']['received']}
}
```

### Step 2: Add Classification Logic (Switch Action)

Add a **Control > Switch** action to triage based on patterns.

**Switch on:** 
```
@{body('Compose')?['subject']} + " " + @{body('Compose')?['body']}
```

**Cases:**

**Case 1: URGENT**
```
Equals (case insensitive):
- *URGENT*
- *CRITICAL*
- *EMERGENCY*
- *DOWN*
- *OUTAGE*
- *PRODUCTION*

Then: Set variable "category" = "urgent"
      Set variable "confidence" = 0.95
      Set variable "reasoning" = "Contains urgent keywords"
```

**Case 2: FOLLOW_UP**
```
Equals (case insensitive):
- *please review*
- *feedback needed*
- *input required*
- *approval*
- *deadline*
- *by EOD*

Then: Set variable "category" = "follow_up"
      Set variable "confidence" = 0.9
      Set variable "reasoning" = "Requires action/input"
```

**Case 3: FYI**
```
Equals (case insensitive):
- *FYI*
- *announcement*
- *schedule*
- *holiday*
- *heads up*

Then: Set variable "category" = "fyi"
      Set variable "confidence" = 0.85
      Set variable "reasoning" = "Informational only"
```

**Case 4: IGNORE** (Default)
```
Contains (sender):
- newsletter@
- promotions@
- marketing@
- noreply@

Then: Set variable "category" = "ignore"
      Set variable "confidence" = 0.95
      Set variable "reasoning" = "Newsletter/marketing email"

Default action: Set category = "fyi"
```

---

## Option 2: Advanced - Parse JSON Action (Recommended)

Create a reusable triage step using JSON parsing.

### Step 1: Create a Triage JSON Template

Create a file `.scripts/email-triage-worker/triage-flow.json`:

```json
{
  "triageRules": {
    "urgent": [
      {
        "type": "keyword",
        "patterns": ["URGENT", "CRITICAL", "EMERGENCY", "DOWN", "OUTAGE"],
        "fields": ["subject", "body"],
        "confidence": 0.95
      },
      {
        "type": "sender",
        "patterns": ["oncall@", "alerts@", "emergency@"],
        "confidence": 0.9
      }
    ],
    "follow_up": [
      {
        "type": "keyword",
        "patterns": ["please review", "feedback needed", "approval", "decision"],
        "fields": ["subject", "body"],
        "confidence": 0.9
      },
      {
        "type": "sender",
        "patterns": ["manager@", "director@", "cto@"],
        "confidence": 0.8
      }
    ],
    "fyi": [
      {
        "type": "keyword",
        "patterns": ["FYI", "announcement", "schedule", "heads up"],
        "fields": ["subject", "body"],
        "confidence": 0.85
      }
    ],
    "ignore": [
      {
        "type": "sender",
        "patterns": ["newsletter@", "promotions@", "noreply@"],
        "confidence": 0.95
      }
    ]
  }
}
```

### Step 2: Power Automate Flow

**Flow: Triage Email**

```
Trigger: When an email arrives

Actions:

1. Parse JSON
   Content: @{triggerOutputs()['body']}
   Schema: (Email schema from trigger)

2. Compose - Email Text
   Inputs: @{concat(body('Parse JSON')?['subject'], ' ', body('Parse JSON')?['body'])}

3. Variables - Initialize
   Name: category
   Type: String
   Value: (empty)

4. Variables - Initialize
   Name: confidence
   Type: Number
   Value: 0

5. Variables - Initialize
   Name: reasoning
   Type: String
   Value: (empty)

6. Condition - Check URGENT
   If @{or(
     contains(body('Compose'), 'URGENT'),
     contains(body('Compose'), 'CRITICAL'),
     contains(body('Compose'), 'EMERGENCY'),
     contains(body('Compose'), 'DOWN'),
     contains(triggerOutputs()['headers']['from'], 'oncall@'),
     contains(triggerOutputs()['headers']['from'], 'alerts@')
   )}
   
   Then:
   - Set variable "category" = "urgent"
   - Set variable "confidence" = 0.95
   - Set variable "reasoning" = "Contains urgent keywords or from alert sender"

7. Condition - Check FOLLOW_UP
   If @{and(
     not(equals(variables('category'), 'urgent')),
     or(
       contains(body('Compose'), 'please review'),
       contains(body('Compose'), 'feedback needed'),
       contains(body('Compose'), 'approval'),
       contains(triggerOutputs()['headers']['from'], 'manager@')
     )
   )}
   
   Then:
   - Set variable "category" = "follow_up"
   - Set variable "confidence" = 0.9
   - Set variable "reasoning" = "Requires action or input"

8. Condition - Check FYI
   If @{and(
     not(equals(variables('category'), 'urgent')),
     not(equals(variables('category'), 'follow_up')),
     or(
       contains(body('Compose'), 'FYI'),
       contains(body('Compose'), 'announcement'),
       contains(body('Compose'), 'schedule'),
       contains(body('Compose'), 'holiday')
     )
   )}
   
   Then:
   - Set variable "category" = "fyi"
   - Set variable "confidence" = 0.85
   - Set variable "reasoning" = "Informational email"

9. Condition - Check IGNORE
   If @{and(
     not(equals(variables('category'), 'urgent')),
     not(equals(variables('category'), 'follow_up')),
     or(
       contains(triggerOutputs()['headers']['from'], 'newsletter@'),
       contains(triggerOutputs()['headers']['from'], 'promotions@'),
       contains(triggerOutputs()['headers']['from'], 'noreply@')
     )
   )}
   
   Then:
   - Set variable "category" = "ignore"
   - Set variable "confidence" = 0.95
   - Set variable "reasoning" = "Newsletter or marketing email"

10. Else (Default to FYI)
    - Set variable "category" = "fyi"
    - Set variable "confidence" = 0.5
    - Set variable "reasoning" = "No specific rules matched"

11. Send Action Based on Category
    - If category = "urgent": Send email alert, create high-priority task
    - If category = "follow_up": Flag for review, add to task list
    - If category = "fyi": Archive or label as FYI
    - If category = "ignore": Auto-delete or move to spam
```

---

## Option 3: Reusable Subflow (Best Practice)

**Create a child flow that returns triage result:**

### Create Flow: "Email Triage Subflow"

**Inputs:**
- `emailSubject` (string)
- `emailBody` (string)
- `emailFrom` (string)

**Outputs:**
- `category` (string: urgent|follow_up|fyi|ignore)
- `confidence` (number: 0.0-1.0)
- `reasoning` (string)

**Flow Logic:** Same as Option 2, but structured as reusable

### Use in Main Flow:

```
Trigger: When email arrives

1. Call "Email Triage Subflow"
   emailSubject: @{triggerOutputs()['headers']['subject']}
   emailBody: @{triggerOutputs()['headers']['body']}
   emailFrom: @{triggerOutputs()['headers']['from']}

2. Get outputs:
   @{outputs('Email_Triage_Subflow')?['category']}
   @{outputs('Email_Triage_Subflow')?['confidence']}
   @{outputs('Email_Triage_Subflow')?['reasoning']}

3. Action based on category (Switch)
   Case "urgent": Alert user
   Case "follow_up": Add task
   Case "fyi": Archive
   Case "ignore": Delete
```

---

## Comparison: Power Automate vs Cloudflare Worker

| Aspect | Power Automate Native | Cloudflare Worker |
|--------|----------------------|-------------------|
| **Setup** | 5-10 min | 15-20 min (deploy) |
| **Cost** | Premium plan required | Free (first 100k/day) |
| **Speed** | ~2-3s per email | <10ms per email |
| **Customization** | Drag-drop UI | Edit JSON rules |
| **Reusability** | Easy (subflow) | Easy (HTTP endpoint) |
| **Scalability** | Limited to flow quota | Unlimited |
| **Offline** | N/A | Can run local | 

---

## Recommended Setup

**Use Power Automate native for:**
- Simple triage (urgent/everything else)
- Low-volume workflows (<100/day)
- Quick setup without external deployment
- Learning/testing

**Use Cloudflare Worker for:**
- Complex rules (4 categories with many patterns)
- High-volume triage (1000s/day)
- Reuse across multiple systems
- Zero cost at scale

---

## Example Power Automate Flow Code

Export this as `.json` and import into Power Automate:

```json
{
  "definition": {
    "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
    "actions": {
      "Initialize_category": {
        "type": "InitializeVariable",
        "inputs": {
          "variables": [
            {
              "name": "category",
              "type": "string"
            }
          ]
        }
      },
      "Initialize_confidence": {
        "type": "InitializeVariable",
        "inputs": {
          "variables": [
            {
              "name": "confidence",
              "type": "number"
            }
          ]
        }
      },
      "Triage_Logic": {
        "type": "Switch",
        "expression": "@variables('category')",
        "cases": {
          "Urgent": {
            "case": "urgent",
            "actions": {
              "Alert_User": {
                "type": "SendEmail",
                "inputs": {
                  "parameters": {
                    "emailAddress": "you@example.com",
                    "subject": "URGENT EMAIL: @{triggerOutputs()['headers']['subject']}",
                    "body": "High priority email received"
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

---

## Quick Start: 5-Minute Setup

1. **Create flow:** Automated cloud flow → When email arrives (Outlook)
2. **Add Compose:** Combine subject + body
3. **Add Condition:** If contains "URGENT" or "CRITICAL" → Set variable "category" = "urgent"
4. **Add Condition:** Else if contains "review" → Set variable "category" = "follow_up"
5. **Add Action:** Based on category, apply labels/create tasks

Done in under 5 minutes with no coding! 🚀
